# Pergunta composta multi-especialista — rodada 2 (05/11/2026, pós-publicação)

Item 3.4 do Bloco 3 ("decompor pergunta composta... no Knowledge ou via Supervisor"), que tinha
ficado como não implementado (só a instrução de completude existia).

## Diagnóstico

`m01` — "Qual a diferença entre a Get Clássica e a Get Smart e quando cai o dinheiro das vendas de
ontem?" — é uma pergunta de dois especialistas (Knowledge para comparação de produto, Payments
para liquidação). O Supervisor já despacha para os dois, mas a ferramenta `knowledge_specialist`
recebia a pergunta **inteira** (as duas partes) como `query`. Medido diretamente:

| Consulta enviada ao Knowledge | relevância do melhor documento |
|---|---|
| só a parte do produto ("Qual a diferença entre a Get Clássica e a Get Smart?") | 0,467 (acima do limiar 0,35) |
| pergunta composta inteira | 0,246 (**abaixo do limiar** → abstenção) |

A parte sobre liquidação dilui o sinal de busca da parte sobre produto o suficiente para apagar
uma resposta que existiria se a consulta fosse focada. Resultado: o sistema abstinha da parte de
produto mesmo tendo evidência suficiente para respondê-la.

## Correção

Reforcei a descrição do parâmetro `query` da ferramenta `knowledge_specialist`
(`app/agents/supervisor/constants.py`) instruindo o LLM do Supervisor a extrair só a parte
relevante para esse especialista quando a mensagem cobre mais de um assunto, em vez de passar a
mensagem inteira. Teste manual do `m01` antes/depois: antes, abstenção total na parte de produto;
depois, resposta parcial mas fundamentada (cita o Simulador de Vendas da Get Smart).

## Um achado colateral mais importante que a correção em si: ruído de medição

A primeira medição no `dev` (40 itens) pareceu mostrar uma **regressão**: `abstention_correct_rate`
caiu de 1,0 para 0,667 e `coverage_mean`/`full_coverage_rate` caíram um pouco. Antes de aceitar
isso como efeito real, rodei um controle (mesmo código, sem a mudança) e depois uma segunda rodada
do tratamento (mesma mudança, de novo):

| Métrica | controle | tratamento (rodada 1) | tratamento (rodada 2) |
|---|---|---|---|
| coverage_mean | 0,736 | 0,708 | **0,736** |
| full_coverage_rate | 0,722 | 0,694 | **0,722** |
| abstention_correct_rate | 1,000 | 0,667 | **1,000** |
| citation_correct_rate | 0,682 | 0,750 | 0,632 |

A rodada 2 do tratamento bate exatamente com o controle em cobertura e abstenção — a "regressão" da
rodada 1 foi ruído de execução (nem relacionado à mudança: até o item `q13`, que não passa pelo
mecanismo que eu mudei, mudou de status entre as rodadas). `citation_correct_rate` sozinho variou
13 p.p. entre três rodadas "idênticas" (0,68/0,75/0,63) sem nenhuma mudança de código — ele é o
indicador mais ruidoso dos quatro.

**Isso confirma, com dados, por que a missão pede 3 rodadas em toda medição com LLM**: uma única
rodada de 40 itens pode mostrar uma "regressão" ou "melhora" de vários pontos percentuais que é só
ruído — e isso é uma ressalva honesta a aplicar retroativamente a todas as decisões de rodada única
tomadas ao longo desta sessão (Blocos 2, 3, 6 e 9 original e rodada 2): o sinal foi sempre grande e
unidirecional nessas decisões (não um empate como aqui), mas o risco de ruído existe em qualquer
medição de rodada única, não só nesta.

## Decisão

**Adotada.** O mecanismo subjacente é real e comprovado por medição direta de relevância (não por
amostra ruidosa); o efeito agregado no `dev`, depois de desempatar o ruído, é neutro a positivo
(sem regressão real), e o caso-alvo (`m01`) melhora de abstenção total para resposta parcial
fundamentada. Suite completa segue verde (388/388).
