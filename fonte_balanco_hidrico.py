"""
Estresse hídrico estrutural por ativo, do balanço quantitativo da ANA.

A OUTRA METADE DA MATRIZ
------------------------
Seca é anomalia temporal e muda todo mês; estresse hídrico é razão
estrutural entre demanda e disponibilidade e muda por ano. Este
módulo entrega o segundo eixo, para que o cruzamento aconteça na
apresentação e não dentro de um índice só.

POR QUE A JUNÇÃO É POR GEOMETRIA, NUNCA POR CÓDIGO
--------------------------------------------------
O balanço publicado carrega `VERSAO = "BHO 2013 versao 1.3 de
22/07/2014"` em todas as 558.699 feições — é a única versão do
serviço, e usa a base hidrográfica ottocodificada de 2013. A
hidrografia corrente publicada pela própria ANA é a BHO 2017.

Atribuir o ativo à ottobacia de 2017 e depois juntar ao balanço pelo
campo `COBACIA` cruzaria duas codificações diferentes: o mesmo código
não designa a mesma bacia nas duas bases. O resultado é linha vazia
ou, pior, linha errada — e nenhum dos dois levanta exceção.

Aqui se pergunta ao próprio serviço do balanço qual polígono contém o
ponto. A ottocodificação usada é a dele, de ponta a ponta, e o código
volta como informação, não como chave de junção.

O QUE SE BAIXA, E POR QUE SÓ ISSO
---------------------------------
Uma feição por ativo: a microbacia que o contém, com geometria. É a
bacia de que aquele ativo depende, que é a unidade da decisão. Baixar
o entorno inflaria o painel sem acrescentar decisão — uma caixa de
meio grau em São Paulo devolve 10.682 microbacias — e baixar a base
inteira são 558.699 feições. O contexto regional fica como camada de
rede opcional no painel, servida pelo próprio SNIRH.

Uso:
    python fonte_balanco_hidrico.py --ativos exemplo_ativos.csv
"""
import argparse
import json
import time
from datetime import datetime, timezone

import requests

import atribuir_ativos as A
import config as C
import limitador

CACHE = C.DIR_ESTRUT / "balanco_por_ativo.json"


def classificar(pc):
    """Classe da ANA para o balanço quantitativo, em % de consumo.

    Os limites são os do SNIRH. Não se usa escala contínua em mapa
    nem em barra: o campo vai de 0 a 373.185%, e qualquer rampa
    linear vira uma tela de uma cor só com um pixel no extremo.
    """
    if pc is None:
        return None, "sem valor"
    # 65535 é código de ausência, não medida. Ver BH_SENTINELA em
    # config.py para a contagem que sustenta isso.
    if pc == C.BH_SENTINELA:
        return None, "sem informação no balanço"
    for lo, hi, n, rot in C.BH_CLASSES:
        if lo <= pc < hi:
            return n, rot
    return None, "sem valor"


def consultar(sessao, lon, lat, com_geometria=True):
    """Microbacia que contém o ponto, no serviço do balanço."""
    p = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": 4326, "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": f"{C.BH_CAMPO_OTTO},{C.BH_CAMPO_RAZAO},VERSAO,COCURSODAG",
        "returnGeometry": "true" if com_geometria else "false",
        "f": "json",
    }
    ultima = None
    for t in range(C.TENTATIVAS):
        try:
            r = sessao.get(C.BH_QUANT + "/query", params=p, timeout=120)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(d["error"].get("message", "erro do servico"))
            time.sleep(C.PAUSA_S)
            return d.get("features", [])
        except Exception as e:
            ultima = e
            time.sleep(C.PAUSA_S * (2 ** t))
    raise RuntimeError(f"falhou apos {C.TENTATIVAS} tentativas") from ultima


def anel_simplificado(anel, tol=0.002):
    """Reduz o anel preservando a forma, por Douglas-Peucker.

    As microbacias são pequenas — dezenas de km — então a tolerância
    é dez vezes menor que a da camada de seca, que é nacional.
    """
    from shapely.geometry import Polygon
    if len(anel) < 4:
        return anel
    g = Polygon(anel).buffer(0).simplify(tol)
    if g.is_empty:
        return anel
    g = max(g.geoms, key=lambda x: x.area) if g.geom_type == "MultiPolygon" else g
    return [[round(x, 4), round(y, 4)] for x, y in g.exterior.coords]


def main():
    ap = argparse.ArgumentParser(description="Estresse hidrico por ativo.")
    ap.add_argument("--ativos", default="exemplo_ativos.csv")
    ap.add_argument("--refazer", action="store_true")
    a = ap.parse_args()

    limitador.configurar(C.MBIT_S)
    ativos = A.ler_ativos(a.ativos)
    print(f"{len(ativos)} ativos")

    cache = {}
    if CACHE.exists() and not a.refazer:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    s = requests.Session()
    s.headers["User-Agent"] = "MonitorHidrico/1.0 (estudo de risco climatico)"

    novos = 0
    for _, r in ativos.iterrows():
        aid = str(r.ativo)
        if aid in cache and not a.refazer:
            continue
        lon, lat = float(r.geometry.x), float(r.geometry.y)
        f = consultar(s, lon, lat)
        if not f:
            # Ativo fora de qualquer microbacia da base: litoral, ilha,
            # ou lacuna da BHO 2013. Registra-se como ausência medida,
            # não como estresse zero.
            cache[aid] = {"cobacia": None, "pcconsumo": None, "classe": None,
                          "rotulo": "sem microbacia na base", "anel": None}
            print(f"  {aid}: SEM MICROBACIA em {lon},{lat}")
            novos += 1
            continue
        at = f[0]["attributes"]
        pc = at.get(C.BH_CAMPO_RAZAO)
        n, rot = classificar(pc)
        anel = None
        rings = (f[0].get("geometry") or {}).get("rings")
        if rings:
            anel = anel_simplificado(max(rings, key=len))
        cache[aid] = {
            "cobacia": at.get(C.BH_CAMPO_OTTO),
            "cursodagua": at.get("COCURSODAG"),
            "pcconsumo": None if pc == C.BH_SENTINELA else pc,
            "sentinela": pc == C.BH_SENTINELA,
            "classe": n,
            "rotulo": rot,
            "versao": at.get("VERSAO"),
            "anel": anel,
            "consultado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        novos += 1
        v = "sentinela 65535" if pc == C.BH_SENTINELA else f"{pc:.2f}%"
        print(f"  {aid}: ottobacia {at.get(C.BH_CAMPO_OTTO)} · {v} · {rot}")

    C.DIR_ESTRUT.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"\n{novos} consultado(s), {len(cache)} no cache")
    print(f"{CACHE}  ({CACHE.stat().st_size/1e3:.0f} kB)")

    versoes = {v.get("versao") for v in cache.values() if v.get("versao")}
    if versoes:
        print(f"versao da base: {versoes}")
    if len(versoes) > 1:
        print("ATENCAO: mais de uma versao na mesma consulta — conferir.")


if __name__ == "__main__":
    main()
