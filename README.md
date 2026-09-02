# Monitor de Estresse Hídrico e Seca

Monitoramento de estresse hídrico e severidade de seca nos estados
com ativos da empresa, integrando dados de órgãos oficiais,
sobrepondo a localização dos ativos e entregando métricas, série
histórica e detecção de mudança de classe.

Reaproveita o motor de aquisição, a atribuição ativo × polígono e a
disciplina de auditoria do estudo de risco climático da Via Raposo
(SP-270).

---

## A distinção que decide a arquitetura

Seca e estresse hídrico não são o mesmo indicador e **não se fundem
num índice só**.

| | **Seca** | **Estresse hídrico** |
|---|---|---|
| o que mede | anomalia contra o normal local | razão demanda / disponibilidade |
| natureza | temporal, muda todo mês | estrutural, muda por ano |
| fonte | Monitor de Secas, S0–S4 | balanço hídrico da ANA por ottobacia |
| decisão que apoia | contingência, plano de escassez | investimento, realocação, reúso |

Um ativo pode estar em bacia permanentemente estressada sem seca
alguma, ou em bacia folgada sob seca excepcional. Fundir os dois
apaga exatamente a distinção que orienta a decisão.

São **duas camadas independentes**, cruzadas só na apresentação:

```
                    sem seca        em seca
estresse baixo      monitorar       contingência
estresse alto       investimento    prioridade máxima
```

---

## Como rodar

```bash
pip install -r requirements.txt
```

```bash
python fonte_monitor_secas.py
```

Baixa os 145 pacotes mensais do Monitor de Secas (139 MB, sem
credencial) e grava o manifesto. Nas execuções seguintes só busca o
que mudou, comparando ETag.

```bash
python conferir_secas.py
```

Mede a série inteira e aplica as verificações de cobertura, extensão,
convenção, continuidade e validade geométrica.

```bash
python atribuir_ativos.py --ativos exemplo_ativos.csv
```

Atribui a classe de seca a cada ativo, mês a mês, e emite as métricas
pedidas: contagem de ativos em seca, classificação por severidade e
mudanças de classe entre meses.

Os dados ficam **fora do repositório**. `MONITOR_RAIZ` aponta o
diretório de trabalho; sem a variável, usa-se `dados/` ao lado do
código.

---

## Estrutura

```
config.py                fontes, classes de severidade, limiares
limitador.py             balde de fichas; teto de banda durante a
                         transferência, não entre elas
fonte_monitor_secas.py   catálogo + balde S3 + manifesto imutável
seca_camada.py           leitura normalizada e atribuição a pontos
conferir_secas.py        auditoria mensal da série
atribuir_ativos.py       métricas e mudanças de classe por ativo
VERIFICACAO_FONTES.md    o que se encontrou em cada portal oficial
```

---

## Estado

| fase do roteiro | situação |
|---|---|
| 0 — definição | **aguarda o cliente**: quantos ativos, quais estados, qual decisão, qual cadência |
| 1 — malha espacial | pendente (ottobacias) |
| 2 — dados oficiais | **Monitor de Secas concluído e conferido**; balanço hídrico levantado; órgãos estaduais não iniciados |
| 3 — camada complementar | pendente (SPEI, CHIRPS, ERA5-Land) |
| 4 — motor de atribuição | **concluído para a camada de seca** |
| 5 — módulo visual | pendente |
| 6 — operação | parcial: manifesto e detecção de mudança prontos; falta agendamento e alerta |

A base de ativos ainda não existe — `exemplo_ativos.csv` é um
gabarito com dez pontos, usado para exercitar a cadeia inteira.
Trocá-lo pela base real é mudança de entrada, não de código.

---

## Fontes

**Monitor de Secas** (ANA e parceiros) — 145 mapas mensais, julho de
2014 a julho de 2026, polígonos S0–S4 em EPSG:4326. API pública sem
autenticação.

**Balanço hídrico quantitativo** (ANA / SNIRH) — 558.699 microbacias
ottocodificadas com razão demanda/disponibilidade. Versão de 2014
sobre a BHO 2013.

**Outorgas** (SNIRH) — federais e estaduais, superficiais e
subterrâneas, como FeatureServer consultável.

O que foi verificado em cada portal, com os números medidos, está em
[`VERIFICACAO_FONTES.md`](VERIFICACAO_FONTES.md).

---

## Uma observação de método

Este módulo nasce de um estudo em que **sete erros foram encontrados
por verificação, não por falha de execução**: deslocamento de
calendário em anos bissextos, um modelo publicado em duas grades com
diferença de até 6,35 °C, um ano inteiro de memória não inicializada,
cenário truncado, oceano retornando zero e derrubando a média para
205 K, máscara aplicada depois da reamostragem, e uma grade fantasma
nascida de eixos diferentes na quarta casa decimal.

Todos produziam número plausível. Nenhum levantava exceção.

Num **monitor** — que atualiza sozinho todo mês e alimenta decisão sem
alguém reler o resultado a cada ciclo — essa classe de erro é mais
perigosa que num estudo. Por isso `conferir_secas.py` está no
encadeamento e não é ferramenta descartável, e por isso quatro
armadilhas da própria fonte estão documentadas antes do código que as
contorna.

A que mais custaria caro: os polígonos de seca são **aninhados**, e
uma junção espacial ingênua reporta "sem seca" para um ativo em seca
moderada. Verificado em dez pontos de julho de 2026 — erra dois, e
erra sempre na direção que esconde o risco.
