"""
Configuração do módulo de estresse hídrico e seca.

DUAS CAMADAS, NÃO UMA
---------------------
Seca e estresse hídrico não são sinônimos e não se fundem num índice
só. Seca é anomalia temporal contra o normal local, muda todo mês, e
vem do Monitor de Secas. Estresse hídrico é razão estrutural entre
demanda e disponibilidade, muda por ano, e vem do balanço hídrico
quantitativo da ANA. Um ativo pode estar em bacia permanentemente
estressada sem seca alguma, ou em bacia folgada sob seca excepcional
— e a decisão gerencial é oposta nos dois casos.

O cruzamento acontece na matriz 2x2 de `matriz.py`, na apresentação.
Nunca antes.

FONTES AFERIDAS EM 02/09/2026
-----------------------------
Cada endereço abaixo foi consultado, não copiado de documentação.
O que se encontrou está em VERIFICACAO_FONTES.md.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------
# CAMINHOS
# ---------------------------------------------------------------
# Os dados ficam fora do repositorio. MONITOR_RAIZ aponta o diretorio
# de trabalho; sem a variavel, usa-se `dados/` ao lado do codigo.
RAIZ = Path(os.environ.get("MONITOR_RAIZ", Path(__file__).resolve().parent / "dados"))

DIR_SECA = RAIZ / "seca"            # pacotes mensais do Monitor de Secas
DIR_ESTRUT = RAIZ / "estrutural"    # balanço hídrico, ottobacias
DIR_ATIVOS = RAIZ / "ativos"        # base de ativos com coordenada conferida
DIR_SAIDA = RAIZ / "saida"          # atribuição, séries, painel
DIR_LOG = RAIZ / "log"

for d in (DIR_SECA, DIR_ESTRUT, DIR_ATIVOS, DIR_SAIDA, DIR_LOG):
    d.mkdir(parents=True, exist_ok=True)

# Registro imutável do que foi baixado e quando. Num monitor que roda
# sozinho, é o que permite reconstruir qualquer estado passado do
# painel — e provar perante terceiro qual dado sustentou a decisão.
MANIFESTO = DIR_SECA / "manifesto.json"

# ---------------------------------------------------------------
# MONITOR DE SECAS (ANA e parceiros)
# ---------------------------------------------------------------
# O catálogo é a lista canônica de meses publicados. O balde S3 é
# onde os shapefiles moram. Os nomes de arquivo no balde NÃO seguem
# padrão derivável — ver resolver_pacotes() em fonte_monitor_secas.py.
MDS_CATALOGO = "https://apimsbr.ana.gov.br/rest/cms-msne/mapa-monitor"
MDS_TABULAR = "https://apimsbr.ana.gov.br/rpc/v1/dados-tabulares-monitor"
MDS_BALDE = "https://ana-monitor-secas-files.s3.sa-east-1.amazonaws.com/"
MDS_PREFIXO = "uploads/mapas/"

# Categorias de severidade. A ordem é a do próprio Monitor.
#
# ARMADILHA DO CAMPO. No shapefile a categoria vem no atributo
# `uf_codigo` — que não é código de UF nenhum. Quem der um join desse
# campo com uma tabela de unidades federativas recebe silêncio e
# resultado vazio, não exceção.
SECA_CAMPO = "uf_codigo"
SECA_VALOR = "Valor"

SECA_CLASSES = {
    "si": (0, "sem seca", "área monitorada sem indicativo de seca"),
    "s0": (1, "S0 fraca", "seca fraca / anormalmente seco"),
    "s1": (2, "S1 moderada", "seca moderada"),
    "s2": (3, "S2 grave", "seca grave"),
    "s3": (4, "S3 extrema", "seca extrema"),
    "s4": (5, "S4 excepcional", "seca excepcional"),
}

# Acima de qual classe um ativo entra em contingência.
SECA_LIMIAR_ALERTA = 2      # S1 ou pior

# ---------------------------------------------------------------
# BALANÇO HÍDRICO QUANTITATIVO (ANA / SNIRH)
# ---------------------------------------------------------------
# PCCONSUMO é demanda sobre disponibilidade em PORCENTAGEM, por
# microbacia ottocodificada (COBACIA, Pfafstetter).
#
# ATENÇÃO À DATA. Todas as 558.699 feições carregam
# VERSAO = "BHO 2013 versao 1.3 de 22/07/2014". O balanço não é
# atualizado desde 2014 e usa a base hidrográfica de 2013 — enquanto
# a hidrografia corrente publicada é a BHO 2017. Atribuir ativo à
# ottobacia de 2017 e depois juntar ao balanço por COBACIA cruza duas
# ottocodificações diferentes. Ou se usa a malha de 2013 nas duas
# pontas, ou a junção é por geometria, nunca por código.
SNIRH_REST = "https://portal1.snirh.gov.br/arcgis/rest/services"
BH_QUANT = f"{SNIRH_REST}/SNIRH2016/Balanco_hidrico_quantitativo/MapServer/1"
BHO_2017 = f"{SNIRH_REST}/Atlas2020/Bho_2017_BR/MapServer/0"
OUTORGAS_FED = f"{SNIRH_REST}/DADOSABERTOS/outorgas_federais_superficial/FeatureServer/0"

BH_CAMPO_RAZAO = "PCCONSUMO"
BH_CAMPO_OTTO = "COBACIA"

# Classificação da ANA para o balanço quantitativo, em % de consumo
# sobre a vazão de referência. Os limites são os do SNIRH.
#
# O máximo observado na base é 373.185% — uma cabeceira minúscula com
# retirada desproporcional. Escala linear em mapa é inútil; classifica-se.
BH_CLASSES = [
    (0.0, 5.0, 1, "excelente"),
    (5.0, 10.0, 2, "confortável"),
    (10.0, 20.0, 3, "preocupante"),
    (20.0, 40.0, 4, "crítica"),
    (40.0, float("inf"), 5, "muito crítica"),
]

BH_LIMIAR_ALERTA = 3        # preocupante ou pior

# ---------------------------------------------------------------
# REDE
# ---------------------------------------------------------------
# O balde S3 derruba conexão sob rajada: 145 requisições HEAD
# seguidas devolveram 145 falhas de conexão, e as mesmas URLs
# responderam 200 uma a uma. Não é 404 — é defesa do servidor.
MBIT_S = 8
PAUSA_S = 0.4
TENTATIVAS = 4
PAGINA_ARCGIS = 1000        # maxRecordCount do serviço
