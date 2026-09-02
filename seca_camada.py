"""
Leitura normalizada da camada mensal de seca, e atribuição a ativos.

TRÊS ARMADILHAS, TODAS SILENCIOSAS
----------------------------------

1. OS POLÍGONOS SÃO ANINHADOS, NÃO DISJUNTOS.

   Medido em julho de 2026, em EPSG:5880:

       si   8.611.104 km²      s0   4.500.590 km²
       s1   1.448.543 km²      s2      16.289 km²

   `si` cobre o Brasil inteiro e `s0` cobre tudo que está em S0 *ou
   pior* — convenção herdada do U.S. Drought Monitor. A interseção
   confirma: si ∩ s0 = a área inteira de s0, s0 ∩ s1 = a área inteira
   de s1, e assim por diante.

   Consequência: um ponto em seca S1 cai dentro de TRÊS polígonos
   (si, s0, s1). Uma junção espacial ingênua devolve três linhas por
   ativo, e quem pegar a primeira recebe "sem seca" para um ativo em
   seca moderada. Número plausível, nenhuma exceção.

   A regra correta é o MÁXIMO das classes que contêm o ponto. E ela
   é correta nas duas convenções: se os polígonos forem disjuntos —
   como na camada `_isolado`, que só existe em alguns meses — o ponto
   cai em um só e o máximo é ele mesmo. Por isso não se depende de
   qual versão o pacote do mês traz.

2. O CAMPO DA CATEGORIA CHAMA `uf_codigo`.

   Não é código de unidade federativa. Guarda 'si', 's0'...'s4'.
   Quem juntar com uma tabela de UF recebe vazio, não erro.

3. O ESQUEMA MUDA AO LONGO DA SÉRIE.

   Levantado nos 145 pacotes: oito esquemas distintos. O campo do
   nome é `uf_codigo` em 140 meses, `Ind` em 5 e `Uf_Codigo` em 1;
   o campo do nível é `Valor` na maioria, `valor` minúsculo em um,
   `uf_valor` em outro, e AUSENTE em 5. O tipo do nível varia entre
   int32, int64 e texto. Um mês está em EPSG:4674, não 4326. E as
   categorias ausentes no mês simplesmente não têm linha — S3 aparece
   em 128 meses, S4 em 73.

   Por isso a camada é localizada por GEOMETRIA E ESQUEMA, nunca por
   nome de arquivo: os nomes internos vão de `julho14.shp` a
   `202206_MS_IMPACTOS.shp`, sem padrão.
"""
import os
import zipfile

import geopandas as gpd
import pandas as pd

import config as C

# Camadas que existem no pacote e NÃO são a de seca.
_NAO_SECA = ("impacto", "estados_monitor", "uf_brasil", "_cortado")

# Alguns pacotes trazem DUAS versões da mesma camada: a canônica e uma
# `_isolado`, com as classes recortadas para não se sobreporem. As
# duas são legítimas e dão o mesmo resultado sob a regra do máximo,
# mas escolher pela ordem do ZIP faria a série alternar de convenção
# sozinha. Prefere-se sempre a canônica, e registra-se a alternativa.
_SUFIXO_VARIANTE = ("_isolado",)

# Nomes já observados para o campo do nome e do nível da categoria.
_CAMPOS_NOME = ("uf_codigo", "ind", "classe")
_CAMPOS_NIVEL = ("valor", "uf_valor", "nivel")


def caminho_pacote(ano, mes):
    return C.DIR_SECA / f"{ano}{mes:02d}.zip"


def _candidatas(z):
    """Shapefiles que podem ser a camada de seca, em ordem de preferência.

    A ordem é determinística de propósito. `namelist()` devolve a
    ordem física do ZIP, que varia entre pacotes: em junho e julho de
    2025 a variante `_isolado` vem antes da canônica, e um leitor que
    pegue a primeira troca de convenção no meio da série sem avisar.
    """
    nomes = [n for n in z.namelist()
             if n.lower().endswith(".shp")
             and not any(t in os.path.basename(n).lower() for t in _NAO_SECA)]

    def chave(n):
        b = os.path.basename(n).lower()
        variante = any(s in b for s in _SUFIXO_VARIANTE)
        return (variante, b)

    return sorted(nomes, key=chave)


def abrir(ano, mes):
    """Devolve a camada de seca do mês, normalizada.

    Colunas garantidas: `classe` ('si'..'s4'), `nivel` (0..5, inteiro),
    `rotulo`, geometria em EPSG:4326. Uma linha por categoria
    presente no mês.
    """
    p = caminho_pacote(ano, mes)
    if not p.exists():
        raise FileNotFoundError(f"pacote ausente: {p}. Rode fonte_monitor_secas.py")

    z = zipfile.ZipFile(p)
    erros = []
    for nome in _candidatas(z):
        try:
            g = gpd.read_file(f"zip://{p}!{nome}")
        except Exception as e:
            erros.append(f"{nome}: {type(e).__name__}")
            continue
        if not set(g.geom_type) & {"Polygon", "MultiPolygon"}:
            continue
        baixo = {c.lower(): c for c in g.columns}
        if not (set(baixo) & set(_CAMPOS_NOME) or set(baixo) & set(_CAMPOS_NIVEL)):
            continue
        return _normalizar(g, baixo, f"{ano}-{mes:02d}", nome)

    raise ValueError(f"{ano}-{mes:02d}: nenhuma camada de seca reconhecida "
                     f"em {p.name}. tentadas: {erros}")


def _normalizar(g, baixo, ym, nome_interno):
    """Padroniza esquema e confere nome contra nível.

    Quando os dois campos existem, eles têm de concordar. Discordar
    significa que a convenção mudou no meio da série — o que é
    exatamente o tipo de coisa que não pode passar em silêncio num
    monitor mensal.
    """
    inv = {v[0]: k for k, v in C.SECA_CLASSES.items()}

    cn = next((baixo[c] for c in _CAMPOS_NOME if c in baixo), None)
    cv = next((baixo[c] for c in _CAMPOS_NIVEL if c in baixo), None)

    classe = nivel = None
    if cn is not None:
        classe = g[cn].astype(str).str.strip().str.lower()
        desconhecida = set(classe) - set(C.SECA_CLASSES)
        if desconhecida:
            raise ValueError(f"{ym}: categoria desconhecida {desconhecida} "
                             f"em '{cn}' ({nome_interno})")
        nivel = classe.map(lambda c: C.SECA_CLASSES[c][0])

    if cv is not None:
        # o tipo varia entre int32, int64 e texto ao longo da série
        v = pd.to_numeric(g[cv], errors="coerce").astype("Int64")
        if nivel is None:
            fora = set(v.dropna().astype(int)) - set(inv)
            if fora:
                raise ValueError(f"{ym}: nivel fora da tabela {fora} em '{cv}'")
            nivel = v.astype(int)
            classe = nivel.map(inv)
        else:
            # confronto: nome e nível têm de dizer a mesma coisa
            div = g.loc[(v.notna()) & (v.astype(int) != nivel), [cn, cv]]
            if len(div):
                raise ValueError(
                    f"{ym}: '{cn}' e '{cv}' discordam em {len(div)} linha(s):\n"
                    f"{div.head(6).to_string()}")

    if classe is None:
        raise ValueError(f"{ym}: sem campo de categoria em {nome_interno}")

    out = gpd.GeoDataFrame(
        {
            "classe": classe.values,
            "nivel": pd.Series(nivel).astype(int).values,
            "rotulo": [C.SECA_CLASSES[c][1] for c in classe],
        },
        geometry=g.geometry.values,
        crs=g.crs,
    )
    # um mês da série está em EPSG:4674; padroniza-se sem perguntar
    if out.crs is None:
        raise ValueError(f"{ym}: camada sem CRS declarado ({nome_interno})")
    if out.crs.to_epsg() != 4326:
        out = out.to_crs(4326)

    # Geometria inválida é comum na série (auto-interseção nos
    # contornos gerados por vetorização). `sjoin` tolera; `difference`
    # e `intersection` levantam TopologyException no meio de uma
    # varredura de 145 meses. Repara-se na leitura, e registra-se
    # quantas feições precisaram — o número entra na conferência.
    ruins = ~out.geometry.is_valid
    out.attrs["reparadas"] = int(ruins.sum())
    if ruins.any():
        out.loc[ruins, "geometry"] = out.loc[ruins, "geometry"].make_valid()
        # make_valid pode devolver coleção com linhas; fica só o polígono
        out["geometry"] = out.geometry.apply(_so_poligono)

    out.attrs["mes"] = ym
    out.attrs["camada"] = nome_interno
    return out.sort_values("nivel").reset_index(drop=True)


def _so_poligono(g):
    """Descarta partes de dimensão menor que `make_valid` possa criar.

    Sem isto, uma GeometryCollection com um fio de linha entra na
    camada e contamina cálculo de área e junção espacial.
    """
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    partes = [p for p in getattr(g, "geoms", []) if p.geom_type in
              ("Polygon", "MultiPolygon")]
    if not partes:
        return g
    from shapely.ops import unary_union
    return unary_union(partes)


# ---------------------------------------------------------------
def atribuir(ativos, camada):
    """Classe de seca de cada ativo, pelo MÁXIMO das que o contêm.

    `ativos` é um GeoDataFrame de pontos com uma coluna identificadora.
    Devolve o mesmo quadro com `nivel`, `classe` e `rotulo`.

    Ver a armadilha 1 no topo do módulo: `sjoin` sozinho devolve uma
    linha por polígono que contém o ponto, e escolher qualquer uma
    que não seja a de maior nível é errar sem avisar.
    """
    if ativos.crs is None:
        raise ValueError("base de ativos sem CRS declarado")
    pts = ativos.to_crs(camada.crs)

    j = gpd.sjoin(pts[["geometry"]], camada[["nivel", "geometry"]],
                  how="left", predicate="within")
    # o índice do ponto se repete; o máximo colapsa o aninhamento
    nivel = j.groupby(level=0)["nivel"].max()

    r = ativos.copy()
    r["nivel"] = nivel.reindex(ativos.index).astype("Int64")
    inv = {v[0]: k for k, v in C.SECA_CLASSES.items()}
    # `nivel` é Int64 e vem <NA> para ponto fora de todo polígono, isto
    # é, fora da área monitorada naquele mês. Não é "sem seca": até
    # 2023 o Monitor não cobria o país inteiro, e tratar ausência como
    # ausência de seca inventa uma década de tranquilidade no Sudeste.
    # `pd.notna` é obrigatório aqui — NaN é um float verdadeiro, e um
    # teste por veracidade deixa o NaN passar direto para o dicionário.
    r["classe"] = r["nivel"].map(lambda n: inv.get(n) if pd.notna(n) else None)
    r["rotulo"] = r["classe"].map(
        lambda c: C.SECA_CLASSES[c][1] if isinstance(c, str)
        else "fora da área monitorada")
    r.attrs["mes"] = camada.attrs.get("mes")
    return r


def _robusto(op, a, b):
    """Operação booleana que não derruba uma varredura de 145 meses.

    O GEOS falha com "non-noded intersection" em contornos vetorizados
    com vértices a distância nanométrica. `grid_size` arredonda as
    coordenadas antes da operação e resolve; 1 metro é irrelevante
    frente a polígonos de milhares de km² e ao traço do próprio mapa,
    que é desenhado em escala nacional.
    """
    try:
        return op(a, b)
    except Exception:
        pass
    for gs in (0.01, 1.0, 10.0):
        try:
            return op(a, b, grid_size=gs)
        except Exception:
            continue
    raise


def _diferenca(a, b):
    import shapely
    return _robusto(shapely.difference, a, b)


def _uniao(a, b):
    import shapely
    return _robusto(shapely.union, a, b)


def area_por_classe(camada, epsg=5880):
    """Área de cada classe em km², já desfeito o aninhamento.

    Em EPSG:5880 (policônica SIRGAS 2000), a projeção equivalente-área
    usada oficialmente para o Brasil. Medir área em graus devolve
    número sem sentido físico.

    Duas colunas, e a diferença entre elas importa:

      km2_isolado    a classe e só ela. Vale nas duas convenções: com
                     polígonos aninhados a subtração devolve o anel;
                     com polígonos disjuntos não há o que subtrair e
                     devolve a própria área.
      km2_poligono   a área bruta do polígono como está no arquivo.
                     Só significa "esta classe ou pior" quando o mês
                     está na convenção aninhada.

    A EXTENSÃO MONITORADA é a soma de `km2_isolado`, nunca o máximo de
    `km2_poligono`. O máximo só coincide com a extensão nos meses
    aninhados; nos disjuntos devolve a maior classe isolada e faz a
    área monitorada parecer despencar. Foi o que aconteceu ao medir a
    série pela primeira vez: nove "quedas de cobertura" que eram
    artefato da métrica, não do dado.
    """
    # Reprojetar recria invalidez: uma geometria válida em graus pode
    # ficar auto-interceptada depois da mudança de coordenada, e o
    # erro só aparece na primeira operação booleana. Revalida-se aqui,
    # não só na leitura.
    g = camada.to_crs(epsg)
    g["geometry"] = g.geometry.make_valid().apply(_so_poligono)

    linhas, acumulado = [], None
    for _, r in g.sort_values("nivel", ascending=False).iterrows():
        geo = r.geometry
        propria = geo if acumulado is None else _diferenca(geo, acumulado)
        acumulado = geo if acumulado is None else _uniao(acumulado, geo)
        linhas.append({
            "classe": r.classe,
            "nivel": r.nivel,
            "rotulo": r.rotulo,
            "km2_isolado": propria.area / 1e6,
            "km2_poligono": geo.area / 1e6,
        })
    d = pd.DataFrame(linhas).sort_values("nivel").reset_index(drop=True)
    d.attrs["extensao_km2"] = float(d.km2_isolado.sum())
    d.attrs["convencao"] = convencao(d)
    return d


def convencao(areas):
    """'aninhada' ou 'disjunta', deduzido das áreas medidas.

    Se os polígonos forem disjuntos, a área bruta de cada um já é a
    área isolada. Se forem aninhados, a bruta é maior em toda classe
    que não a mais severa. Não se assume: mede-se, porque a série usa
    as duas convenções e nada no arquivo diz qual é.
    """
    if len(areas) < 2:
        return "indeterminada"
    d = areas.sort_values("nivel")
    folga = (d.km2_poligono - d.km2_isolado).iloc[:-1]
    return "disjunta" if (folga.abs() < 1.0).all() else "aninhada"
