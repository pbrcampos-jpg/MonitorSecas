# Verificação das fontes oficiais

Respostas à seção 5 do roteiro — *"verificar antes de estimar prazo"*.
Levantado em **02/09/2026**, por consulta direta a cada endereço, não
por documentação. Onde há número, ele foi medido nos 145 pacotes
baixados.

---

## 1. Monitor de Secas

| pergunta do roteiro | resposta |
|---|---|
| cobertura nacional atual | sim, **8.611.104 km²** |
| desde quando | **abril/2023** já cobre 8.241.945 km² (96%); a extensão plena de 8.611.104 km² se estabiliza em **dezembro/2023** |
| existe API ou só download | **API pública, sem autenticação** |
| formato da série histórica | **shapefile de polígono**, EPSG:4326 |
| categoria por polígono ou grade | **polígono**, dissolvido por classe |
| licença | dado público da ANA; sem cadastro nem chave |

**Série completa e sem buraco.** 145 meses, de **julho de 2014 a julho
de 2026**, todos com pacote disponível. Nenhum mês faltando, nenhum
duplicado no calendário. O acervo inteiro pesa **139 MB** e baixou em
uma execução, sem credencial.

**Endereços.**

```
catálogo   https://apimsbr.ana.gov.br/rest/cms-msne/mapa-monitor
tabular    https://apimsbr.ana.gov.br/rpc/v1/dados-tabulares-monitor
arquivos   https://ana-monitor-secas-files.s3.sa-east-1.amazonaws.com/uploads/mapas/
```

O balde S3 é **público e listável** (`?list-type=2`), o que dispensa
adivinhar nome de arquivo — ver o achado 1 abaixo, que é o motivo de
isso importar.

### A expansão da cobertura, medida

A área monitorada não é constante, e essa é a informação que mais
muda o desenho do módulo:

| a partir de | área monitorada |
|---|---|
| 2014-07 | 1.591.382 km² (Nordeste) |
| 2018-11 | 2.185.378 km² |
| 2020-07 | 3.260.284 km² |
| 2021-06 | 4.991.291 km² |
| 2022-12 | 6.992.366 km² |
| 2023-04 | 8.241.945 km² |
| **2023-12** | **8.611.104 km² (nacional)** |

**Consequência direta.** Um ativo em São Paulo, Manaus ou Porto Alegre
não estava "sem seca" em 2016 — estava **fora do mapa**. Verificado:
em julho de 2016, dos dez pontos de teste, **sete estavam fora da área
monitorada**. Qualquer série histórica que trate ausência como
ausência de seca inventa quase uma década de tranquilidade no Sudeste,
no Sul e no Norte. O módulo separa as duas coisas em coluna própria.

### Defasagem operacional

Em 02/09/2026 o mapa mais recente publicado é o de **julho/2026**,
divulgado em 14/08/2026. A cadência é mensal com **cerca de seis
semanas de atraso**. Um monitor que rode todo dia 1º encontra dado
novo em aproximadamente metade das execuções — o agendamento deve
reagir à publicação, não ao calendário.

---

## 2. Balanço hídrico quantitativo da ANA

| pergunta do roteiro | resposta |
|---|---|
| nível de ottobacia disponível | **microbacia ottocodificada**, campo `COBACIA` |
| data da última atualização | **22/07/2014**, sobre a BHO de 2013 |

```
https://portal1.snirh.gov.br/arcgis/rest/services/SNIRH2016/Balanco_hidrico_quantitativo/MapServer/1
```

**558.699 polígonos**, consultáveis por REST (`Map,Query,Data`), com
paginação de 1.000 por requisição. O campo `PCCONSUMO` é a razão
demanda/disponibilidade em porcentagem — exatamente a métrica de
estresse hídrico estrutural.

**Duas ressalvas que mudam o plano.**

1. **O dado tem doze anos.** Todas as 558.699 feições carregam
   `VERSAO = "BHO 2013 versao 1.3 de 22/07/2014"`. Não é uma
   atualização atrasada: é a única versão publicada nesse serviço.
   Sustenta decisão de investimento — que é estrutural e muda devagar
   — mas não deve ser apresentado como retrato corrente da demanda.

2. **A ottocodificação do balanço é a de 2013; a hidrografia corrente
   publicada é a BHO 2017** (`Atlas2020/Bho_2017_BR`). Atribuir o
   ativo à ottobacia de 2017 e depois juntar ao balanço **por código**
   cruza duas codificações diferentes. Ou se usa a malha de 2013 nas
   duas pontas, ou a junção é por geometria. Junção por `COBACIA`
   entre bases de anos diferentes devolve linha vazia ou, pior, linha
   errada — sem erro.

**Faixa dos valores.** `PCCONSUMO` vai de 0 a **373.185%**. Escala
linear em mapa é inútil; a classificação da ANA (excelente /
confortável / preocupante / crítica / muito crítica) está em
`config.py`.

### Um sentinela disfarçado de medida

**2.210 feições têm `PCCONSUMO` exatamente 65535** — que é 2¹⁶ − 1.
A faixa inteira de 60.000 a 70.000 tem **21 feições** fora esse valor.
Um pico de 105× num único número, numa faixa por onde a distribuição
mal passa, não é medida: é código de "sem informação" gravado num
campo numérico. `PCCONSUMO IS NULL` não devolve nenhum registro — a
ausência só se manifesta assim.

São 0,4% da base, e bastou isso para atingir **1 dos 10 pontos de
ensaio**. Sem tratar, o ativo entra como "muito crítica" e sobe ao
topo do painel como o mais estressado do conjunto, sobre um valor que
não existe. O módulo o registra como ausência e o mantém **fora da
matriz 2×2** — sem os dois eixos não há célula que o descreva.

### Acesso, e por que a junção é por geometria

O serviço aceita consulta espacial por ponto e devolve a microbacia
que o contém, com geometria — o que dispensa baixar as 558.699
feições e, mais importante, **evita a junção por código**. Atribuir o
ativo à ottobacia da BHO 2017 e depois juntar ao balanço por
`COBACIA` cruzaria duas ottocodificações diferentes: o mesmo código
não designa a mesma bacia nas duas bases, e o resultado é linha vazia
ou linha errada, sem exceção. Perguntando ao próprio serviço do
balanço, a codificação é a dele de ponta a ponta e o código volta
como informação, não como chave.

O contexto regional sai do `export` do próprio MapServer, que
responde PNG por caixa (a extensão WMS está declarada mas o
`GetCapabilities` devolve 400).

---

---

## 3. Outorgas

```
DADOSABERTOS/outorgas_federais_superficial/FeatureServer/0
DADOSABERTOS/outorgas_estaduais_superficial/FeatureServer/0
DADOSABERTOS/outorgas_estaduais_subterraneas/FeatureServer/0
```

Publicadas como **FeatureServer**, isto é, consultáveis por atributo e
por geometria. A metade da demanda que o roteiro pedia está acessível.
Não foram inventariadas em profundidade nesta rodada — a prioridade
era destravar a camada de seca.

## 4. Órgãos estaduais

**Não verificado.** Depende de saber quais estados entram, que é a
pergunta 2 da seção 7 do roteiro. É o item mais fragmentado do
projeto e o único da seção 5 que continua em aberto.

---

## Cinco achados que teriam virado erro silencioso

Todos foram encontrados por conferência, não por exceção. Nenhum
levantava erro; todos produziam número plausível. O quinto é o
sentinela 65535 do balanço, descrito na seção 2; os quatro abaixo
são da camada de seca.

### 1. O nome do arquivo não é derivável

Julho de 2026 está em `julho2026.zip`. Abril de 2015, não está em
`abril2015.zip`. O balde guarda `Abril15.zip`, `fevereiro21.zip`,
`setembro2020.zip`, `monitor_outubro18.zip`, `fev19.zip` e
`março2026.zip` — maiúscula variável, ano de dois ou quatro dígitos,
prefixo às vezes, acento às vezes, abreviação às vezes.

Testado: **o padrão simples não resolve nenhum mês anterior a 2019**.
Como o balde é listável, o módulo casa o conteúdo real contra o
catálogo. Adivinhar teria produzido série com buraco, e mês faltando
vira "sem seca" no painel, não erro.

Quatorze meses têm **dois** ZIPs (variação de caixa, prefixo ou
acento). A escolha é determinística e fica registrada no manifesto,
com os candidatos rejeitados ao lado — sem isso, duas execuções podem
pegar arquivos diferentes para o mesmo mês.

### 2. Os polígonos são aninhados, não disjuntos

Medido em julho de 2026, em EPSG:5880:

| classe | área do polígono |
|---|---|
| si | 8.611.104 km² |
| s0 | 4.500.590 km² |
| s1 | 1.448.543 km² |
| s2 | 16.289 km² |

`si` cobre o país inteiro e `s0` cobre tudo que está em S0 **ou pior**
— convenção herdada do U.S. Drought Monitor. A interseção confirma:
si ∩ s0 é a área inteira de s0.

**Um ponto em seca S1 cai dentro de três polígonos.** Uma junção
espacial ingênua devolve três linhas por ativo, e quem pegar a
primeira recebe "sem seca" para um ativo em seca moderada.

Demonstrado com dez pontos em julho de 2026: a junção ingênua erra
**dois de dez**, e erra na direção que esconde risco — São Paulo, que
está em **S1 moderada**, aparece como "sem seca"; Belo Horizonte, em
S0, idem.

A regra correta é o **máximo** das classes que contêm o ponto, e ela
vale nas duas convenções.

### 3. O campo da categoria se chama `uf_codigo`

Não é código de unidade federativa. Guarda `si`, `s0` … `s4`. Quem
juntar esse campo com uma tabela de UF recebe resultado vazio, não
exceção.

### 4. O esquema muda ao longo da série

Levantado nos 145 pacotes: **oito esquemas de atributo distintos**.

- o campo do nome é `uf_codigo` em 140 meses, `Ind` em 5, `Uf_Codigo` em 1
- o campo do nível é `Valor`, `valor`, `uf_valor` — ou **ausente**, em 5 meses
- o tipo do nível varia entre `int32`, `int64` e texto
- **um mês está em EPSG:4674**, não 4326
- categorias ausentes no mês não têm linha: S3 aparece em 133 meses, S4 em 78
- o nome interno do shapefile vai de `julho14.shp` a `202206_MS_IMPACTOS.shp`
- alguns pacotes trazem **duas versões** da mesma camada, a canônica e
  uma `_isolado` com as classes recortadas; em junho e julho de 2025 a
  variante vem **antes** no ZIP, e um leitor que pegue a primeira troca
  de convenção no meio da série sem avisar
- **um mês (2018-11) está gravado na convenção disjunta**, não aninhada

Por isso a camada é localizada por **geometria e esquema**, nunca por
nome de arquivo, e o nome da categoria é conferido contra o nível
numérico sempre que os dois existem.

---

## Estado da conferência da série

Rodando `conferir_secas.py` sobre os 145 meses:

- **145 meses lidos, 0 erros de leitura**
- extensão monitorada **monótona**, de 1.591.382 a 8.611.105 km²
- **144 meses aninhados, 1 disjunto** (2018-11)
- **4 feições com geometria inválida**, reparadas na leitura
  (2019-03, 2019-04, 2019-05, 2022-02)
- 29 saltos de área entre meses consecutivos acima de 2,5×, quase
  todos em S0 e S1 nos anos de cobertura pequena — **são avisos, não
  defeitos**: a seca fraca é a classe mais volátil e a razão fica
  ruidosa em área pequena

Uma armadilha da própria conferência, registrada porque quase passou:
a primeira versão media a extensão como o **máximo** da área bruta dos
polígonos. Isso só equivale à extensão nos meses aninhados; nos
disjuntos devolve a maior classe isolada e faz a área monitorada
parecer despencar. Gerou **nove falsos alarmes de queda de cobertura**
antes de a métrica ser trocada pela soma das áreas isoladas, que vale
nas duas convenções.

---

## O que isto libera do cronograma

A fase 2 do roteiro era apontada como o **maior risco de prazo**, por
depender de portal de terceiro. Para o Monitor de Secas esse risco
**não se materializou**: API aberta, série completa, sem credencial,
139 MB, e a rotina de atualização mensal já implementada e conferida.

O risco remanescente da fase 2 é o **balanço hídrico** — não por
acesso, que é livre, mas por **idade do dado** — e os **órgãos
estaduais**, que continuam sem verificação por dependerem da definição
dos estados-alvo.
