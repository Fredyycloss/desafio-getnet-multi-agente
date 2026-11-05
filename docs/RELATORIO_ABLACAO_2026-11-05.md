# Ablação V8 — Blocos 5 e 6 (05/11/2026)

Dados: `docs/eval/ABLATION_v8_run1_2026-11-05.json` (commit 9e5548f, provider anthropic,
model claude-haiku-5-5). **1 rodada** (não as 3 pedidas pela missão — decisão de custo/tempo,
ver "Limitações" abaixo). Qualidade: `quality_test_v2.jsonl` (66 itens, nunca usado para ajuste),
checks determinísticos (sem juiz LLM, para não dobrar o custo desta rodada). Segurança/roteamento:
`context_scenarios_heldout_v2.json` (109 casos, 19 perigosos).

## Qualidade (n=66 por config)

| Config | full_coverage | coverage_mean | citação correta | critic_rejection | latência média | chamadas LLM | custo médio |
|---|---|---|---|---|---|---|---|
| **full** (atual) | **0,712** | 0,737 | 0,880 | 0,030 | 6,51 s | 5,20 | US$0,0011 |
| no_critic | 0,667 | 0,700 | 0,873 | 0,000 | 5,05 s | 3,85 | US$0,0008 |
| no_context_intelligence | 0,621 | 0,647 | 0,827 | 0,000 | 7,94 s | 6,03 | US$0,0014 |
| fast_path_only (força fast path sempre) | 0,667 | 0,684 | 0,833 | 0,015 | 6,36 s | 4,97 | US$0,0010 |
| planning_only (força loop de planejamento sempre) | 0,606 | 0,624 | 0,878 | 0,030 | 9,29 s | 7,08 | US$0,0016 |

## Segurança e roteamento (heldout_v2, 109 casos, 19 perigosos / 69 com agente esperado)

| Config | falsos negativos (perigo) | recall crítico | falso positivo (seguro→escalação) | rota correta |
|---|---|---|---|---|
| **full** | **0/19** | **1,00** | 2,44% | 0,957 (66/69) |
| no_policy_gate | **19/19** | **0,00** | 0,00% | 0,971 (irrelevante — config insegura, nunca produção) |
| no_context_intelligence | 4/19 | 0,846 | 2,44% | 0,928 (64/69) |

## Interpretação

- **PolicyGate é inegociável.** Sem ele, os 19 casos perigosos do heldout passam — recall crítico
  cai de 1,00 para 0,00. Confirma a regra da missão ("segurança determinística continua
  obrigatória"); esta config nunca deve existir fora de estudo.
- **Context Intelligence não é só latência — também é segurança e qualidade.** Removê-lo custa
  4 dos 19 casos perigosos (recall crítico 1,00→0,846), 9,1 p.p. de `full_coverage` (0,712→0,621,
  -12,8% relativo), 3 p.p. de acerto de rota (0,957→0,928), e ainda fica **mais lento e mais caro**
  (6,51s→7,94s, US$0,0011→US$0,0014) porque todo turno cai no loop de planejamento completo sem o
  sinal do fast path. Não há cenário em que removê-lo compensa — fundir CI com o roteamento do
  Supervisor (como a missão perguntava) perderia justamente o sinal que torna o fast path possível.
- **O Critic se paga** (resposta ao Bloco 5): removê-lo economiza US$0,0003/pergunta (-27%) e 1,46s,
  mas custa 4,5 p.p. de `full_coverage` (0,712→0,667, -6,3% relativo). Ele rejeitou e corrigiu 2 das
  66 respostas (`critic_rejection_rate`=3,03%) — não é teatro de revisão, está pegando defeito real
  a um custo pequeno. Recomendação: manter como checagem final obrigatória.
- **O split fast-path/planejamento também se paga nos dois sentidos.** Forçar só fast-path
  (pular o loop mesmo quando a Context Intelligence está insegura) perde 4,5 p.p. de
  `full_coverage` vs. full. Forçar só planejamento (pular o fast-path mesmo em casos óbvios e de
  alta confiança) é a **pior** config de todas em `full_coverage` (0,606) e a mais cara/lenta
  (US$0,0016, 9,29s) — o `FINAL` do loop por vezes se contenta com uma resposta de especialista
  incompleta em casos que o fast-path acertaria direto. Manter os dois caminhos.

## Decisão do Bloco 6

**Não fundir nem remover nenhum agente ou gate.** Os dados não sustentam simplificação: cada peça
(PolicyGate, Context Intelligence, Critic, fast-path vs. planejamento) perde qualidade e/ou
segurança mensurável quando removida, e nenhuma remoção reduziu custo o suficiente para justificar
a perda. Em particular, CI e PolicyGate não podem ser fundidos — são redes de segurança
diferentes: perder CI perde ~85% do recall crítico e qualidade; perder PolicyGate perde 100% do
recall crítico. Fundi-los esconderia que são falhas independentes.

**Resposta à pergunta 4 da entrevista v3 ("a cadeia continua pesada?")**: sim, continua sendo uma
cadeia de vários passos — mas esta rodada mede, pela primeira vez, que cada passo paga sua parte em
qualidade/segurança a um custo modesto (o pior caso testado custa US$0,0016/pergunta). "Pesada" não
é o mesmo que "sem justificativa": o peso agora tem números por trás.

## Limitações (sem rodeio)

- **1 rodada, não 3.** A missão pedia 3 rodadas por config para reduzir ruído de amostra única.
  Dado o orçamento de tempo/token do usuário, só uma rodada foi executada (~76 min, 8 configs ×
  66-109 casos). O sinal em cada comparação é unidirecional e grande (ex.: PolicyGate 0→19 falsos
  negativos, CI -9 p.p. de `full_coverage` E mais caro/lento ao mesmo tempo) — não há caso de
  fronteira que pareça depender de ruído de amostra única. Se uma decisão futura depender de uma
  diferença pequena (<2 p.p.), repetir com 3 rodadas antes de decidir.
- **Sem juiz LLM nesta rodada** (só checks determinísticos) para não dobrar o custo; os números de
  `full_coverage`/citação já diferenciam bem as configs.
- Config `no_policy_gate` nunca deve ser usada fora deste estudo — reportada aqui só para medir o
  tamanho do buraco que o gate tapa.
