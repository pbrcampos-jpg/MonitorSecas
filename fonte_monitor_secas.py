"""
Aquisição dos pacotes mensais do Monitor de Secas.

POR QUE NÃO SE MONTA O NOME DO ARQUIVO
--------------------------------------
A tentação é óbvia: o mapa de julho de 2026 está em
`uploads/mapas/julho2026.zip`, logo o de abril de 2015 estaria em
`abril2015.zip`. Testado nos 145 meses publicados: o padrão simples
não resolve NENHUM mês anterior a 2019. O balde guarda `Abril15.zip`,
`fevereiro21.zip`, `setembro2020.zip`, `monitor_outubro18.zip`,
`fev19.zip` e `março2026.zip` — maiúscula variável, ano de dois ou
quatro dígitos, prefixo às vezes, acento às vezes, abreviação às
vezes.

Como o balde é público e LISTÁVEL, não se adivinha: lista-se o
conteúdo real e casa-se contra o catálogo da API, que é a lista
canônica dos meses publicados. Adivinhar produziria série com buraco
silencioso — e mês faltando vira "sem seca" no painel, não erro.

O QUE SE GRAVA
--------------
Cada download entra no manifesto com chave, ETag, tamanho e data de
publicação no balde, mais os candidatos rejeitados. Catorze meses têm
mais de um ZIP e a escolha precisa ser reproduzível: sem o registro,
duas execuções podem pegar arquivos diferentes para o mesmo mês e
ninguém percebe.

Uso:
    python fonte_monitor_secas.py                # baixa o que falta
    python fonte_monitor_secas.py --tudo         # refaz a série toda
    python fonte_monitor_secas.py --mes 2026-07  # um mês
"""
import argparse
import json
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

import config as C
import limitador

NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
# Abreviações observadas no balde. Só as que existem; uma nova é
# denunciada por conferir_secas.py em vez de virar mês perdido.
ABREV = {"fev": 2, "mar": 3, "abr": 4, "jun": 6, "jul": 7,
         "set": 9, "out": 10, "dez": 12}


def sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _sessao():
    s = requests.Session()
    s.headers["User-Agent"] = "MonitorHidrico/1.0 (estudo de risco climatico)"
    return s


def _pedir(sessao, url, **kw):
    """GET com recuo exponencial.

    O balde derruba conexão sob rajada: 145 requisições seguidas
    devolveram 145 falhas, e as mesmas URLs responderam 200 uma a
    uma. A falha chega como erro de conexão, não como código HTTP —
    quem só testar `r.status_code` não vê nada.
    """
    ultima = None
    for t in range(C.TENTATIVAS):
        try:
            r = sessao.get(url, timeout=kw.pop("timeout", 120), **kw)
            r.raise_for_status()
            time.sleep(C.PAUSA_S)
            return r
        except Exception as e:
            ultima = e
            time.sleep(C.PAUSA_S * (2 ** t))
    raise RuntimeError(f"falhou apos {C.TENTATIVAS} tentativas: {url}") from ultima


# ---------------------------------------------------------------
def ler_catalogo(sessao):
    """Lista canônica dos meses publicados, da API do Monitor.

    A API pagina em 100 e ignora limite maior, então se percorre.
    """
    itens, pagina = {}, 1
    while True:
        r = _pedir(sessao, C.MDS_CATALOGO, params={"limit": 100, "page": pagina})
        d = r.json()
        for x in d["list"]:
            itens[(x["ano"], x["mes"])] = x
        p = d.get("paginator", {}).get("page", {})
        if not p or p.get("current", 1) >= p.get("total", 1):
            break
        pagina += 1
    return dict(sorted(itens.items()))


def listar_balde(sessao):
    """Conteúdo real do prefixo de mapas, com ETag e tamanho."""
    obj, token = [], None
    while True:
        p = {"list-type": "2", "prefix": C.MDS_PREFIXO, "max-keys": "1000"}
        if token:
            p["continuation-token"] = token
        r = _pedir(sessao, C.MDS_BALDE, params=p)
        x = ET.fromstring(r.content)
        for c in x.findall("s:Contents", NS):
            obj.append({
                "chave": c.find("s:Key", NS).text,
                "tamanho": int(c.find("s:Size", NS).text),
                "etag": c.find("s:ETag", NS).text.strip('"'),
                "publicado": c.find("s:LastModified", NS).text,
            })
        if x.find("s:IsTruncated", NS).text != "true":
            break
        token = x.find("s:NextContinuationToken", NS).text
    return obj


# ---------------------------------------------------------------
_PAT = re.compile(
    r"(?:^|[/_])(" + "|".join(list(MESES) + list(ABREV)) + r")[_ ]?(\d{2,4})(?=\D|$)"
)


def datar(chave):
    """(ano, mes) a partir do nome do arquivo, ou None."""
    base = sem_acento(chave.split("/")[-1]).lower()
    m = _PAT.search("_" + base)
    if not m:
        return None
    nome, a = m.group(1), int(m.group(2))
    mes = MESES.get(nome) or ABREV[nome]
    return (a if a > 1000 else 2000 + a, mes)


def _preferencia(o):
    """Desempate entre ZIPs do mesmo mês. Menor é melhor.

    Catorze meses têm dois arquivos. A regra não é estética: é para
    que a série não mude sozinha entre execuções. Prefere-se o nome
    canônico (mês por extenso, ano de quatro dígitos, sem prefixo) e,
    em empate, o arquivo maior — que é o mais completo quando um dos
    dois é recorte parcial.
    """
    b = sem_acento(o["chave"].split("/")[-1]).lower().removesuffix(".zip")
    m = _PAT.search("_" + b)
    extenso = 0 if m and m.group(1) in MESES else 1
    ano4 = 0 if m and len(m.group(2)) == 4 else 1
    limpo = 0 if m and m.start() <= 1 else 1      # sem prefixo tipo "monitor_"
    return (extenso, ano4, limpo, -o["tamanho"], o["chave"])


def resolver_pacotes(catalogo, objetos):
    """Casa cada mês do catálogo com um ZIP real do balde.

    Devolve (achados, faltando, extras). `faltando` é o número que
    importa conferir antes de prometer série histórica a alguém.
    """
    porm = {}
    for o in objetos:
        if not o["chave"].lower().endswith(".zip"):
            continue
        d = datar(o["chave"])
        if d:
            porm.setdefault(d, []).append(o)

    achados, faltando = {}, []
    for ym in catalogo:
        cand = sorted(porm.get(ym, []), key=_preferencia)
        if not cand:
            faltando.append(ym)
            continue
        achados[ym] = {"escolhido": cand[0], "alternativos": cand[1:]}
    return achados, faltando, sorted(set(porm) - set(catalogo))


# ---------------------------------------------------------------
def carregar_manifesto():
    if C.MANIFESTO.exists():
        return json.loads(C.MANIFESTO.read_text(encoding="utf-8"))
    return {}


def gravar_manifesto(m):
    C.MANIFESTO.write_text(
        json.dumps(dict(sorted(m.items())), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def baixar(sessao, ym, pacote, manifesto, forcar=False):
    esc = pacote["escolhido"]
    destino = C.DIR_SECA / f"{ym[0]}{ym[1]:02d}.zip"
    chave = f"{ym[0]}-{ym[1]:02d}"
    reg = manifesto.get(chave)

    # Idempotência: só rebaixa se o ETag do balde mudou. Num monitor
    # mensal isso é a diferença entre 1 download e 145.
    if not forcar and reg and destino.exists() and reg.get("etag") == esc["etag"]:
        return "mantido"

    url = C.MDS_BALDE + requests.utils.quote(esc["chave"])
    dados = limitador.baixar(sessao.get, url)
    if len(dados) != esc["tamanho"]:
        raise IOError(f"{chave}: baixou {len(dados)} B, "
                      f"balde anuncia {esc['tamanho']} B")
    destino.write_bytes(dados)

    manifesto[chave] = {
        "chave_s3": esc["chave"],
        "etag": esc["etag"],
        "tamanho": esc["tamanho"],
        "publicado": esc["publicado"],
        "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "arquivo": destino.name,
        "alternativos": [a["chave"] for a in pacote["alternativos"]],
    }
    return "novo" if not reg else "atualizado"


# ---------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Baixa os pacotes do Monitor de Secas.")
    ap.add_argument("--tudo", action="store_true",
                    help="rebaixa mesmo se o ETag bater")
    ap.add_argument("--mes", help="um mes so, no formato AAAA-MM")
    a = ap.parse_args()

    limitador.configurar(C.MBIT_S)
    s = _sessao()

    print("lendo catalogo do Monitor de Secas...")
    cat = ler_catalogo(s)
    pri, ult = list(cat)[0], list(cat)[-1]
    print(f"  {len(cat)} meses publicados: "
          f"{pri[0]}-{pri[1]:02d} a {ult[0]}-{ult[1]:02d}")

    print("listando o balde S3...")
    obj = listar_balde(s)
    nzip = sum(1 for o in obj if o["chave"].lower().endswith(".zip"))
    print(f"  {len(obj)} objetos, {nzip} ZIPs")

    pac, faltando, extras = resolver_pacotes(cat, obj)
    print(f"  resolvidos {len(pac)}/{len(cat)} meses")
    if faltando:
        print(f"  SEM PACOTE ({len(faltando)}): {faltando}")
    if extras:
        print(f"  ZIP sem mes no catalogo ({len(extras)}): {extras}")
    dup = {k: v for k, v in pac.items() if v["alternativos"]}
    if dup:
        print(f"  {len(dup)} meses com mais de um ZIP; escolha no manifesto")

    alvo = list(pac)
    if a.mes:
        y, m = a.mes.split("-")
        alvo = [(int(y), int(m))]

    man = carregar_manifesto()
    conta, t0 = {}, time.monotonic()
    for ym in alvo:
        if ym not in pac:
            print(f"  {ym[0]}-{ym[1]:02d}  SEM PACOTE")
            continue
        try:
            r = baixar(s, ym, pac[ym], man, forcar=a.tudo)
        except Exception as e:
            r = "falha"
            print(f"  {ym[0]}-{ym[1]:02d}  FALHA: {type(e).__name__}: {e}")
        conta[r] = conta.get(r, 0) + 1
        if r != "mantido":
            print(f"  {ym[0]}-{ym[1]:02d}  {r}")

    gravar_manifesto(man)
    print(f"\n{conta}")
    print(f"manifesto: {C.MANIFESTO}")
    if limitador._global:
        print(f"banda media: {limitador._global.mbit_s_medio(t0):.1f} Mbit/s")


if __name__ == "__main__":
    main()
