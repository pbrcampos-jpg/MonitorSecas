"""
Prepara o JSON do painel de seca.

TRÊS DECISÕES QUE VALE REGISTRAR
--------------------------------

1. AGREGAÇÃO POR GRADE EQUIVALENTE-ÁREA, NÃO POR INTERSEÇÃO.

   Para saber quanto de cada estado está em cada classe seriam
   precisas 145 × 27 × 6 interseções de polígono — caro e frágil, já
   que quatro meses da série têm geometria inválida.

   Em vez disso amostra-se uma grade regular de 10 km em EPSG:5880,
   que é projeção equivalente-área: cada célula vale exatamente a
   mesma superfície, então contar célula é medir área. Cada ponto é
   atribuído ao seu estado UMA vez, e a cada mês só se refaz a
   atribuição de classe — que é junção espacial com índice, barata.

   É a mesma escolha do estudo tomado como referência: calcular na
   célula e agregar só na apresentação. Agregar antes destrói o
   extremo, que aqui é justamente S3 e S4.

2. GEOMETRIA SIMPLIFICADA PARA 2 km, COORDENADA EM GRADE DE 0,01°.

   Medido: o mês bruto ocupa 1,48 MB de GeoJSON; simplificado a 0,02°
   e arredondado a 0,01° cai para 0,066 MB, com **0,005% de erro de
   área**. Os 145 meses cabem em ~9,5 MB. O polígono de origem é
   desenhado em escala nacional; guardar a quarta casa decimal seria
   guardar ruído de digitalização.

3. O DESENHO USA A ORDEM, NÃO O RECORTE.

   Os polígonos são aninhados (`si` contém todos os demais). Em vez de
   recortar classe por classe — caro e sujeito a sliver — o mapa
   desenha do menos severo para o mais severo e deixa o pintor
   resolver. Dá o mesmo resultado visual e vale também no único mês
   gravado na convenção disjunta.

Uso:
    python exportar_painel.py
    python exportar_painel.py --ativos exemplo_ativos.csv
"""
import argparse
import json
import warnings
import zipfile
from datetime import datetime, timezone

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

import atribuir_ativos as A
import config as C
import fonte_balanco_hidrico
import fonte_monitor_secas as F
import seca_camada as S

warnings.filterwarnings("ignore")

TOL = 0.02          # simplificação, em grau (~2 km)
GRADE_COORD = 0.01  # arredondamento da coordenada (~1 km)
PASSO_KM = 10       # lado da célula de amostragem, em km
ESC = 100           # coordenada gravada como inteiro: grau x 100

# Paleta oficial do Monitor de Secas (a mesma do U.S. Drought Monitor).
CORES = {
    "si": "#f2f2f0", "s0": "#ffff00", "s1": "#fcd37f",
    "s2": "#ffaa00", "s3": "#e60000", "s4": "#730000",
}

# Paleta do estresse estrutural. DELIBERADAMENTE em outra família —
# azul-esverdeado para roxo, não amarelo para vermelho. Os dois eixos
# não se somam, e paleta parecida convidaria a lê-los como se
# fossem o mesmo tipo de coisa em intensidades diferentes.
CORES_ESTRUT = {
    1: "#d9f0ea", 2: "#9ed8c8", 3: "#6ba8bd",
    4: "#4a6fa5", 5: "#3d3a7a",
}
COR_SEM_INFO = "#c9c6bb"


def _estrut(reg):
    """Registro de estresse do ativo, enxuto para o painel."""
    if not reg:
        return None
    return {
        "cobacia": reg.get("cobacia"),
        "pc": reg.get("pcconsumo"),
        "n": reg.get("classe"),
        "rotulo": reg.get("rotulo"),
        "sentinela": bool(reg.get("sentinela")),
        "anel": reg.get("anel"),
    }


def malha_uf():
    """Limites estaduais, do próprio pacote do Monitor.

    Vêm de dentro do ZIP de propósito: é a mesma malha que o órgão usa
    para desenhar o mapa, então estado e seca casam por construção.

    Aqui `uf_codigo` é de fato a sigla do estado — ao contrário da
    camada de seca, onde o mesmo nome de campo guarda a categoria.
    """
    for chave in sorted(F.carregar_manifesto(), reverse=True):
        ano, mes = (int(x) for x in chave.split("-"))
        p = C.DIR_SECA / f"{ano}{mes:02d}.zip"
        for n in zipfile.ZipFile(p).namelist():
            if n.lower().endswith("uf_brasil.shp"):
                g = gpd.read_file(f"zip://{p}!{n}")
                return g.rename(columns={"uf_codigo": "uf",
                                         "uf_nome": "nome"})[["uf", "nome", "geometry"]]
    raise FileNotFoundError("nenhum pacote traz UF_Brasil.shp")


def grade(ufs):
    """Pontos de amostragem de 10 km, já com o estado de cada um.

    Em EPSG:5880 a célula tem área constante, então a contagem de
    pontos é proporcional à área — que é o que permite somar por
    estado sem interseção de polígono.
    """
    u = ufs.to_crs(5880)
    x0, y0, x1, y1 = u.total_bounds
    p = PASSO_KM * 1000
    xs = np.arange(x0 + p / 2, x1, p)
    ys = np.arange(y0 + p / 2, y1, p)
    X, Y = np.meshgrid(xs, ys)
    g = gpd.GeoDataFrame(geometry=gpd.points_from_xy(X.ravel(), Y.ravel()),
                         crs=5880)
    g = gpd.sjoin(g, u[["uf", "geometry"]], how="inner", predicate="within")
    g = g[~g.index.duplicated(keep="first")]          # ponto na divisa
    g["km2"] = (PASSO_KM ** 2)
    return g.drop(columns="index_right").to_crs(4326).reset_index(drop=True)


def _aneis(geo):
    """Anéis externos como lista plana de inteiros (grau x 100).

    Buraco de polígono é ignorado: na escala nacional deste painel os
    furos das feições de seca são menores que a própria simplificação.
    """
    out = []
    partes = geo.geoms if geo.geom_type == "MultiPolygon" else [geo]
    for p in partes:
        if p.is_empty:
            continue
        c = np.asarray(p.exterior.coords)
        v = np.round(c * ESC).astype(int)
        # remove ponto repetido depois do arredondamento
        m = np.any(np.diff(v, axis=0) != 0, axis=1)
        v = np.vstack([v[:1], v[1:][m]])
        if len(v) >= 4:
            out.append(v.ravel().tolist())
    return out


def main():
    ap = argparse.ArgumentParser(description="Gera o JSON do painel de seca.")
    ap.add_argument("--ativos", default="exemplo_ativos.csv")
    ap.add_argument("--desde", type=int)
    a = ap.parse_args()

    print("montando a malha estadual e a grade de amostragem...")
    ufs = malha_uf()
    gr = grade(ufs)
    print(f"  {len(ufs)} estados, {len(gr):,} celulas de {PASSO_KM} km "
          f"({len(gr) * PASSO_KM ** 2:,} km2)")

    ativos = A.ler_ativos(a.ativos)
    print(f"  {len(ativos)} ativos")

    chaves = sorted(F.carregar_manifesto())
    if a.desde:
        chaves = [k for k in chaves if int(k[:4]) >= a.desde]

    ordem = [c for c, _ in sorted(C.SECA_CLASSES.items(), key=lambda x: x[1][0])]
    idx = {c: i for i, c in enumerate(ordem)}

    geo, nac, por_uf, por_ativo = [], [], {}, {}
    for u in ufs.uf:
        por_uf[u] = []

    for n, chave in enumerate(chaves, 1):
        ano, mes = (int(x) for x in chave.split("-"))
        g = S.abrir(ano, mes)

        # --- geometria para desenho
        h = g.copy()
        h["geometry"] = shapely.set_precision(
            h.geometry.simplify(TOL).values, GRADE_COORD)
        h = h[~h.geometry.is_empty]
        geo.append([{"c": int(r.nivel), "r": _aneis(r.geometry)}
                    for _, r in h.sort_values("nivel").iterrows()])

        # --- medida por célula: nacional, por estado, por ativo
        cel = S.atribuir(gr, g)
        cl = cel.nivel.fillna(-1).astype(int)

        cont = np.bincount(cl[cl >= 0], minlength=len(ordem)) * (PASSO_KM ** 2)
        nac.append({"mes": chave,
                    "km2": [int(x) for x in cont],
                    "extensao": int(cont.sum())})

        d = pd.DataFrame({"uf": cel.uf.values, "n": cl.values})
        d = d[d.n >= 0]
        tab = (d.groupby(["uf", "n"]).size().unstack(fill_value=0)
               * (PASSO_KM ** 2))
        for u in ufs.uf:
            linha = [0] * len(ordem)
            if u in tab.index:
                for k, v in tab.loc[u].items():
                    linha[int(k)] = int(v)
            por_uf[u].append(linha)

        at = S.atribuir(ativos, g)
        for i, r in at.iterrows():
            por_ativo.setdefault(str(r.ativo), []).append(
                int(r.nivel) if pd.notna(r.nivel) else -1)

        if n % 24 == 0 or n == len(chaves):
            print(f"  {n}/{len(chaves)}  {chave}")

    # --- camada estrutural, uma consulta já feita e em cache
    estrut = {}
    if fonte_balanco_hidrico.CACHE.exists():
        estrut = json.loads(
            fonte_balanco_hidrico.CACHE.read_text(encoding="utf-8"))
        print(f"  estresse estrutural: {len(estrut)} ativos em cache")
    else:
        print("  SEM camada estrutural — rode fonte_balanco_hidrico.py")

    bbox = [float(x) for x in ufs.total_bounds]
    saida = {
        "meta": {
            "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "meses": chaves,
            "bbox": bbox,
            "escala": ESC,
            "passo_km": PASSO_KM,
            "tolerancia_grau": TOL,
            "fonte": "Monitor de Secas (ANA e parceiros)",
            "bh_servico": C.BH_QUANT.rsplit("/", 1)[0],
        },
        "classes": [{"k": c, "n": C.SECA_CLASSES[c][0],
                     "rotulo": C.SECA_CLASSES[c][1], "cor": CORES[c]}
                    for c in ordem],
        "limiar_alerta": C.SECA_LIMIAR_ALERTA,
        "geo": geo,
        "nacional": nac,
        "uf": {u: {"nome": ufs.set_index("uf").nome[u], "km2": por_uf[u]}
               for u in ufs.uf},
        # Classes do estresse estrutural. Ficam separadas das de seca
        # de propósito: são eixos diferentes, e uma paleta comum
        # convidaria a somar os dois num número só.
        "classes_estrut": [{"n": n, "rotulo": rot, "cor": CORES_ESTRUT[n],
                            "de": lo, "ate": (None if hi == float("inf") else hi)}
                           for lo, hi, n, rot in C.BH_CLASSES],
        "limiar_estrut": C.BH_LIMIAR_ALERTA,
        "estrut_versao": next((v.get("versao") for v in estrut.values()
                               if v.get("versao")), None),
        "ativos": [{"id": str(r.ativo),
                    "nome": str(r.get("nome", r.ativo)),
                    "uf": str(r.get("uf", "")),
                    "lon": round(float(r.geometry.x), 4),
                    "lat": round(float(r.geometry.y), 4),
                    "s": por_ativo[str(r.ativo)],
                    "e": _estrut(estrut.get(str(r.ativo)))}
                   for _, r in ativos.iterrows()],
        "contorno": [{"uf": r.uf, "r": _aneis(
            shapely.set_precision(r.geometry.simplify(TOL), GRADE_COORD))}
            for _, r in ufs.iterrows()],
    }

    dest = C.DIR_SAIDA / "painel_seca.json"
    dest.write_text(json.dumps(saida, ensure_ascii=False,
                               separators=(",", ":")), encoding="utf-8")
    print(f"\n{dest.name}: {dest.stat().st_size / 1e6:.1f} MB")

    # conferência: a grade tem de reproduzir a área dos polígonos
    ext_grade = nac[-1]["extensao"]
    ext_pol = S.area_por_classe(S.abrir(*(int(x) for x in chaves[-1].split("-"))))
    ep = ext_pol.attrs["extensao_km2"]
    print(f"conferencia da grade em {chaves[-1]}: "
          f"{ext_grade:,} km2 contra {ep:,.0f} km2 do poligono "
          f"({100 * abs(ext_grade - ep) / ep:.2f}% de diferenca)")


if __name__ == "__main__":
    main()
