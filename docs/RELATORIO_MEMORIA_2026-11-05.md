# Memória V8 — Bloco 9 (05/11/2026)

30 conversas longas (16 turnos cada: 1ª mensagem + 14 preenchimentos + pergunta final sobre um fato
só dito na 1ª mensagem), `SESSION_MEMORY` ligado × desligado, avaliadas por palavra-chave **e** por
juiz LLM (claude-haiku-5-5, rubrica própria). Dados: `docs/eval/MEMORY_EVAL_v8_run1_2026-11-05.json`
(rodada 1, os dois modos) e `docs/eval/MEMORY_EVAL_v8_run2_on_2026-11-05.json` (rodada 2, só modo
`on`, depois dos dois ajustes abaixo).

## Rodada 1 — resultado bruto e um bug encontrado

| Modo | recall (palavra-chave) | recall (juiz) |
|---|---|---|
| `off` (sem memória) | 0,067 (2/30) | 0,000 (0/30) |
| `on` (com memória) | 0,667 (20/30) | 0,633 (19/30) |

Investigando o log descobri que o token do `/api/auth/demo-login` expira perto da marca de 1h, e a
rodada de 30 conversas no modo `on` leva ~1h — os **últimos 4 casos** (`goal_revenue_en`,
`seasonal_pt`, `accessibility_en`, `loyalty_program_pt`) bateram em `401 Unauthorized` e voltaram
com resposta vazia. O modo `off` não foi afetado (terminou antes da marca de 1h). Excluindo os 4
casos corrompidos (não por falha real de memória, por bug de autenticação do script de avaliação):

| Modo `on`, corrigido (26 casos válidos) | recall (palavra-chave) | recall (juiz) |
|---|---|---|
| | 0,769 (20/26) | 0,731 (19/26) |

## Dois ajustes aplicados

1. **Bug do token** (`backend/app/evaluation/run_memory_eval.py`): login repetido a cada conversa
   em vez de uma vez por modo — elimina a corrupção acima para qualquer rodada futura, qualquer
   duração.
2. **Padrão "sabe mas nega"** — em `product_interest_en`, `opening_year_pt` (rodada 1) o modelo
   recuperava o fato certo do resumo da sessão mas respondia negando: *"você não disse isso nas
   mensagens, mas o resumo interno indica que..."* — exatamente o tipo de inflação que a v3 criticou
   no avaliador por palavra-chave (bate a palavra, mas a resposta nega o fato). Em
   `knowledge_agent.py::_recall_conversation` o campo `source` passou a dizer explicitamente que
   `conversation_memory` carrega fatos que o cliente já disse antes, com a mesma confiança de uma
   citação literal — não é uma fonte separada ou menos confiável.

## Rodada 2 (só modo `on`, com os dois ajustes)

| | recall (palavra-chave) | recall (juiz) |
|---|---|---|
| `on`, rodada 2 | 0,733 (22/30) | 0,700 (21/30) |

O bug de autenticação não se repetiu (nenhuma resposta vazia). O padrão "sabe mas nega" **só foi
parcialmente corrigido**: `product_interest_en` e `seasonal_pt` ainda exibem o mesmo problema na
rodada 2 ("você não disse... mas o resumo indica..." — ver exemplos abaixo). O ajuste de texto não
foi suficiente para eliminá-lo; fica como item aberto.

## Causas dos casos que não recuperam (amostra das duas rodadas)

| Causa | Exemplos | Observação |
|---|---|---|
| (A) Menu de esclarecimento intercepta antes da recuperação | `open_days_en`, `supplier_name_pt` (rodada 1); `shop_name_en` (rodada 2) | A Context Intelligence classifica a pergunta como ambígua e mostra o menu de tópicos antes de qualquer especialista tentar `recall_conversation`. Reaparece em casos diferentes nas duas rodadas — parece sensível a variação do roteamento, não é um caso isolado. **Não corrigido nesta rodada** (tocar no prompt da CI arrisca regredir os Blocos 1–4 sem medição dedicada). |
| (B) Caiu em atendimento humano em vez do especialista | `ticket_size_pt` (rodada 1) | Roteamento, mesma família do item (A). |
| (C) "Sabe mas nega" — recupera o fato, mas afirma que o cliente não disse | `product_interest_en`, `opening_year_pt` (rodada 1); `product_interest_en`, `seasonal_pt` (rodada 2) | Ajuste de texto aplicado, mitigou parcialmente, não eliminou. Provável causa residual: o prompt de geração (`_generate()`) não distingue explicitamente `conversation_memory` de fonte "menos confiável" na instrução do system prompt, só no próprio payload da ferramenta. |
| (D) Dado de ferramenta (ao vivo) tem prioridade sobre o fato da conversa | `card_brand_pref_pt` (rodada 1) | O especialista consultou transações reais (sem bandeira) em vez de usar o fato já dito pelo cliente ("uso mais Elo"). Não corrigido. |
| Falso negativo do avaliador por palavra-chave (não é falha real) | `competitor_en` (rodada 1): o juiz credita corretamente uma recuperação parafraseada que a palavra-chave não reconhece | Confirma o motivo de ter o juiz: a palavra-chave sozinha erra em ambas as direções (infla em (C), subestima aqui). |

## Meta (≥28/30, 93%) — não atingida, sem rodeio

Rodada 1 corrigida: 73–77%. Rodada 2: 70–73%. Os dois números são consistentes entre si (dentro da
variação esperada de uma amostra de 26–30 casos) e bem abaixo da meta. A memória claramente ajuda
muito (70–77% com memória vs. 0–7% sem) — a lacuna que falta fechar está nos quatro padrões da
tabela acima, principalmente (A)/(B) (roteamento intercepta antes da memória ser tentada) e (C)
(modelo nega um fato que ele mesmo recuperou).

## Métricas auxiliares (rodada 1, modo `on`)

- Compressão de contexto: resumo médio substitui 8.113 caracteres de histórico por uma nota de
  914,5 caracteres (~8,9×) quando a memória é usada.
- Custo: 260 chamadas de resumo em segundo plano (US$0,057 no total, modo `on`) + 30 chamadas de
  juiz por modo (~US$0,02 por modo). Nada caro — o gargalo desta rodada foi tempo de parede
  (~1h por modo), não dinheiro.

## O que ficou para uma próxima rodada

- Resolver (A)/(B) de verdade exige medir o prompt da Context Intelligence para esse tipo de
  pergunta sem regredir os heldouts de segurança/roteamento já fechados nos Blocos 1 e 6 — não
  tentado aqui por risco/tempo.
- Resolver (C) por completo provavelmente exige uma instrução explícita no system prompt de
  `_generate()` (não só no payload da ferramenta) dizendo para tratar `conversation_memory` como
  fala direta do cliente.
- Só 2 das 3 rodadas da missão foram executadas no total entre as duas rodadas (1 completa nos dois
  modos + 1 parcial só no `on`) — orçamento de tempo. O sinal é consistente entre as duas, mas uma
  terceira rodada completa reduziria a incerteza da estimativa.
