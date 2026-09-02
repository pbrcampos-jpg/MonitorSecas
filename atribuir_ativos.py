"""
Atribuição de seca por ativo, mês a mês.

Entrega as duas métricas que o requisito pede — contagem total de
ativos sob seca e classificação por nível de severidade — mais a
série mensal por ativo, que é o que permite responder "está piorando
aqui?" em vez de só "como está hoje".

FORA DO MAPA NÃO É SEM SECA
---------------------------
O Monitor nasceu cobrindo só o Nordeste, com 1.591.382 km², e só
alcançou os 8.611.104 km² do país em 2023. Um ativo em São Paulo não
estava "sem seca" em 2016: estava fora da área monitorada. Por isso a
classe `None` existe e é distinta de `si`, e por isso a contagem de
ativos monitorados aparece em toda linha do resumo — sem ela, a série
histórica inventa uma década de tranquilidade no Sudeste e no Sul.

ENTRADA
-------
CSV ou GeoPackage com uma coluna identificadora e coordenadas em grau
decimal, WGS84. Por padrão procura `id`, `longitude` e `latitude`.

    python atribuir_ativos.py --ativos dados/ativos/ativos.csv
    python atribuir_ativos.py --ativos ... --desde 2023
    python atribuir_ativos.py --ativos ... --mes 2026-07
"""
import argparse

import geopandas as gpd
import pandas as pd

import config as C
import fonte_monitor_secas as F
import seca_camada as S


def ler_ativos(caminho, col_id="id", col_lon="longitude", col_lat="latitude"):
    """Lê a base de ativos e confere o que costuma vir errado.

    Coordenada trocada, grau em texto com vírgula decimal e ponto fora
    do Brasil são os três defeitos que aparecem em toda planilha de
    cadastro. Nenhum levanta exceção sozinho: viram ativo no oceano,
    silenciosamente fora de qualquer polígono e portanto "sem seca".
    """
    p = str(caminho)
    if p.lower().endswith((".gpkg", ".shp", ".geojson")):
        g = gpd.read_file(p)
        if g.crs is None:
            raise ValueError("base sem CRS declarado")
        return g.to_crs(4326)

    d = pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")
    faltam = [c for c in (col_id, col_lon, col_lat) if c not in d.columns]
    if faltam:
        raise ValueError(f"colunas ausentes: {faltam}. tem: {list(d.columns)}")

    for c in (col_lon, col_lat):
        if d[c].dtype == object:
            d[c] = pd.to_numeric(
                d[c].astype(str).str.strip().str.replace(",", ".", regex=False),
                errors="coerce")

    ruim = d[d[col_lon].isna() | d[col_lat].isna()]
    if len(ruim):
        raise ValueError(f"{len(ruim)} ativo(s) sem coordenada legível: "
                         f"{list(ruim[col_id])[:8]}")

    # Caixa do Brasil com folga. Longitude e latitude trocadas caem
    # fora dela em todo o território nacional, que é o ponto.
    fora = d[(d[col_lon] < -75) | (d[col_lon] > -33) |
             (d[col_lat] < -34) | (d[col_lat] > 6)]
    if len(fora):
        raise ValueError(
            f"{len(fora)} ativo(s) fora da caixa do Brasil — confira se "
            f"longitude e latitude estão trocadas:\n"
            f"{fora[[col_id, col_lon, col_lat]].head(8).to_string(index=False)}")

    g = gpd.GeoDataFrame(
        d, geometry=gpd.points_from_xy(d[col_lon], d[col_lat]), crs=4326)
    g = g.rename(columns={col_id: "ativo"})
    if g.ativo.duplicated().any():
        dup = list(g.ativo[g.ativo.duplicated()].unique())[:8]
        raise ValueError(f"identificador repetido na base: {dup}")
    return g


def serie(ativos, desde=None, mes=None):
    """Série mensal de classe de seca por ativo."""
    man = F.carregar_manifesto()
    chaves = sorted(man)
    if mes:
        chaves = [k for k in chaves if k == mes]
    if desde:
        chaves = [k for k in chaves if int(k[:4]) >= desde]
    if not chaves:
        raise ValueError("nenhum mês selecionado; rode fonte_monitor_secas.py")

    partes = []
    for k in chaves:
        ano, m = (int(x) for x in k.split("-"))
        g = S.abrir(ano, m)
        r = S.atribuir(ativos, g)
        r["mes"] = k
        partes.append(pd.DataFrame(r.drop(columns="geometry")))
    return pd.concat(partes, ignore_index=True)


def resumir(s):
    """Contagem por mês: monitorados, em seca, e por nível."""
    linhas = []
    for mes, d in s.groupby("mes"):
        mon = d.nivel.notna()
        r = {
            "mes": mes,
            "ativos": len(d),
            "monitorados": int(mon.sum()),
            "fora_do_mapa": int((~mon).sum()),
            "em_seca": int((d.nivel.fillna(-1) >= 1).sum()),
            "em_alerta": int((d.nivel.fillna(-1) >= C.SECA_LIMIAR_ALERTA).sum()),
        }
        for c, (n, _, _) in C.SECA_CLASSES.items():
            r[c] = int((d.nivel == n).sum())
        linhas.append(r)
    return pd.DataFrame(linhas).sort_values("mes").reset_index(drop=True)


def mudancas(s):
    """Ativos que mudaram de classe de um mês para o outro.

    É o gatilho do monitor. Sem isto o painel mostra estado e ninguém
    percebe a transição, que é justamente o que exige decisão.
    """
    d = s.sort_values(["ativo", "mes"]).copy()
    d["ant"] = d.groupby("ativo")["nivel"].shift(1)
    d["mes_ant"] = d.groupby("ativo")["mes"].shift(1)
    m = d[d.ant.notna() & d.nivel.notna() & (d.ant != d.nivel)].copy()
    m["direcao"] = m.apply(
        lambda r: "agravou" if r.nivel > r.ant else "aliviou", axis=1)
    m["degraus"] = (m.nivel - m.ant).abs().astype(int)
    return m[["mes", "ativo", "mes_ant", "ant", "nivel", "rotulo",
              "direcao", "degraus"]].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="Atribui seca aos ativos.")
    ap.add_argument("--ativos", required=True, help="CSV ou camada de ativos")
    ap.add_argument("--id", default="id")
    ap.add_argument("--lon", default="longitude")
    ap.add_argument("--lat", default="latitude")
    ap.add_argument("--desde", type=int, help="ano inicial")
    ap.add_argument("--mes", help="um mes so, AAAA-MM")
    a = ap.parse_args()

    ativos = ler_ativos(a.ativos, a.id, a.lon, a.lat)
    print(f"{len(ativos)} ativos lidos de {a.ativos}")

    s = serie(ativos, a.desde, a.mes)
    r = resumir(s)
    m = mudancas(s)

    s.to_csv(C.DIR_SAIDA / "ativos_seca_mensal.csv", index=False,
             encoding="utf-8-sig")
    r.to_csv(C.DIR_SAIDA / "ativos_seca_resumo.csv", index=False,
             encoding="utf-8-sig")
    m.to_csv(C.DIR_SAIDA / "ativos_seca_mudancas.csv", index=False,
             encoding="utf-8-sig")

    print(f"\nultimos meses:")
    print(r.tail(6).to_string(index=False))
    fora = r.fora_do_mapa.iloc[-1]
    if fora:
        print(f"\nATENCAO: {fora} ativo(s) fora da area monitorada no ultimo "
              f"mes. Isso NAO e ausencia de seca.")
    if len(m):
        u = m[m.mes == r.mes.iloc[-1]]
        print(f"\n{len(u)} mudanca(s) de classe no ultimo mes "
              f"({(u.direcao == 'agravou').sum()} agravaram)")
    print(f"\nsaida em {C.DIR_SAIDA}")


if __name__ == "__main__":
    main()
