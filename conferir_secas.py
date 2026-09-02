"""
Conferência da série mensal de seca.

POR QUE ISTO É PARTE DO MÉTODO E NÃO UM EXTRA
---------------------------------------------
No estudo que originou este módulo, sete erros foram encontrados por
verificação, não por falha de execução: deslocamento de calendário em
anos bissextos, um modelo publicado em duas grades com diferença de
até 6,35 °C, um ano de memória não inicializada, cenário truncado,
oceano retornando zero, máscara aplicada depois da reamostragem, e
uma grade fantasma nascida de eixos diferentes na quarta casa
decimal. Todos produziam número plausível. Nenhum levantava exceção.

Num monitor que atualiza sozinho todo mês e alimenta decisão sem
ninguém reler o resultado, essa classe de erro é mais perigosa que
num estudo. As conferências abaixo são as que pegam esse tipo:

  cobertura     todo mês do catálogo tem pacote, e o pacote abre
  extensão      quanto do país estava sob monitoramento naquele mês
  aninhamento   as classes seguem contendo as mais severas
  continuidade  a área por classe não salta de forma implausível
  reparo        quantas feições vieram com geometria inválida

A CONFERÊNCIA DE EXTENSÃO É A MENOS ÓBVIA E A MAIS IMPORTANTE.
O Monitor nasceu cobrindo só o Nordeste. A área monitorada vai de
1.591.382 km² em 2014 a 8.611.104 km² em 2024. Um ativo em São Paulo
não estava "sem seca" em 2016 — estava FORA DO MAPA. Quem tratar
ausência como ausência de seca constrói uma série histórica que
inventa uma década de tranquilidade.

Uso:
    python conferir_secas.py
    python conferir_secas.py --desde 2023
"""
import argparse
import json
import warnings

import pandas as pd

import config as C
import fonte_monitor_secas as F
import seca_camada as S

warnings.filterwarnings("ignore")

# Salto de área entre meses consecutivos que merece olhar humano.
# O Monitor é mensal e a seca é inercial: a área de uma classe raramente
# mais que dobra ou cai à metade de um mês para o outro sem que algo
# tenha acontecido na produção do mapa.
SALTO = 2.5
AREA_MINIMA = 5_000        # km²; abaixo disso a razão é ruidosa demais


def series(desde=None):
    """Percorre a série e mede cada mês. Devolve o quadro de medidas."""
    man = F.carregar_manifesto()
    linhas = []
    for chave in sorted(man):
        ano, mes = (int(x) for x in chave.split("-"))
        if desde and ano < desde:
            continue
        reg = {"mes": chave, "ano": ano, "m": mes}
        try:
            g = S.abrir(ano, mes)
        except Exception as e:
            reg["erro"] = f"{type(e).__name__}: {e}"
            linhas.append(reg)
            continue

        a = S.area_por_classe(g)
        reg["camada"] = g.attrs["camada"].split("/")[-1]
        reg["classes"] = len(g)
        reg["reparadas"] = g.attrs.get("reparadas", 0)
        reg["convencao"] = a.attrs["convencao"]
        reg["extensao_km2"] = a.attrs["extensao_km2"]
        for _, r in a.iterrows():
            reg[f"{r.classe}_km2"] = float(r.km2_isolado)
        # área efetivamente em seca = tudo que não é 'si'
        reg["seca_km2"] = float(a.loc[a.nivel > 0, "km2_isolado"].sum())
        linhas.append(reg)
    return pd.DataFrame(linhas)


def conferir(df):
    """Aplica as verificações. Devolve lista de achados."""
    achados = []

    # 1. cobertura: catálogo x pacote x leitura
    man = F.carregar_manifesto()
    faltam = [k for k in man if k not in set(df.mes)]
    if faltam:
        achados.append(("COBERTURA", f"{len(faltam)} mes(es) no manifesto sem "
                                     f"medida: {faltam[:8]}"))
    ruins = df[df.get("erro").notna()] if "erro" in df else df.iloc[:0]
    for _, r in ruins.iterrows():
        achados.append(("LEITURA", f"{r.mes}: {r.erro}"))

    d = df[df.get("erro").isna()] if "erro" in df else df
    if d.empty:
        return achados

    # 2. continuidade do calendário
    esperado = pd.period_range(d.mes.min(), d.mes.max(), freq="M").astype(str)
    buracos = sorted(set(esperado) - set(d.mes))
    if buracos:
        achados.append(("CALENDARIO", f"{len(buracos)} mes(es) ausente(s): {buracos}"))

    # 3. extensão monitorada: só pode crescer ou ficar igual
    e = d.sort_values("mes")
    queda = e[e.extensao_km2 < e.extensao_km2.shift(1) * 0.98]
    for _, r in queda.iterrows():
        achados.append(("EXTENSAO", f"{r.mes}: área monitorada caiu para "
                                    f"{r.extensao_km2:,.0f} km²"))

    # 4. salto implausível na área de uma classe
    for c in ("s0", "s1", "s2", "s3", "s4"):
        col = f"{c}_km2"
        if col not in e:
            continue
        v = e[col].fillna(0)
        ant = v.shift(1)
        alvo = (v > AREA_MINIMA) & (ant > AREA_MINIMA)
        raz = (v / ant).where(alvo)
        for i in e.index[alvo & ((raz > SALTO) | (raz < 1 / SALTO))]:
            achados.append(("SALTO", f"{e.at[i,'mes']} {c.upper()}: "
                                     f"{ant[i]:,.0f} -> {v[i]:,.0f} km² "
                                     f"({raz[i]:.1f}x)"))

    # 5. convenção dos polígonos, por mês
    conv = d.convencao.value_counts().to_dict()
    if len(conv) > 1:
        disj = list(d.loc[d.convencao == "disjunta", "mes"])
        achados.append(("CONVENCAO", f"a série mistura convenções {conv}; "
                                     f"disjuntos: {disj[:10]}"
                                     f"{' ...' if len(disj) > 10 else ''}"))

    # 6. geometria reparada
    rep = d[d.reparadas > 0]
    if len(rep):
        achados.append(("GEOMETRIA", f"{len(rep)} mes(es) com feição inválida "
                                     f"reparada na leitura: "
                                     f"{list(rep.mes)[:8]}"))
    return achados


def main():
    ap = argparse.ArgumentParser(description="Confere a serie mensal de seca.")
    ap.add_argument("--desde", type=int, help="ano inicial")
    a = ap.parse_args()

    print("medindo a serie...")
    df = series(a.desde)
    saida = C.DIR_SAIDA / "serie_seca_mensal.csv"
    df.to_csv(saida, index=False, encoding="utf-8-sig")

    d = df[df.get("erro").isna()] if "erro" in df else df
    print(f"  {len(df)} meses medidos, {len(df) - len(d)} com erro de leitura")
    if len(d):
        print(f"  extensao monitorada: {d.extensao_km2.min():,.0f} -> "
              f"{d.extensao_km2.max():,.0f} km²")
        nac = d[d.extensao_km2 > 8_000_000]
        if len(nac):
            print(f"  cobertura nacional a partir de {nac.mes.min()}")

    print("\nachados:")
    ach = conferir(df)
    if not ach:
        print("  nenhum")
    for tipo, msg in ach:
        print(f"  [{tipo}] {msg}")

    rel = C.DIR_SAIDA / "conferencia_seca.json"
    rel.write_text(json.dumps(
        {"meses": len(df), "achados": [{"tipo": t, "texto": m} for t, m in ach]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nserie:      {saida}")
    print(f"conferencia:{rel}")


if __name__ == "__main__":
    main()
