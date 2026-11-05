# Relatório de geração — V8 Bloco 3

Ataca as causas (c) contexto certo mas a geração errou/omitiu, (d) pergunta composta incompleta e
(e) citação para trecho errado, identificadas no Bloco 1 (12/18 = 67% dos casos imperfeitos).
Decidido no `answer_quality_dev.jsonl` (40 itens, baseline medido antes de qualquer mudança);
confirmado uma vez no `answer_quality_test.jsonl` (23) e no `quality_test_v2.jsonl` (66, nunca
usado para ajuste).

## Mudanças (`backend/app/agents/knowledge_agent.py`, `_generate`)

1. **Instrução de completude**: "If the question has more than one part, answer every part; do
   not silently drop one." Ataca (d) — q13/q28/m01 do Bloco 1 eram exatamente isso.
2. **Instrução de prioridade da evidência**: "If a draft fact you were about to write conflicts
   with the evidence, follow the evidence, never your own assumption or general knowledge." Ataca
   (c) — q26 e m02 do Bloco 1 eram o modelo contradizendo a evidência citada por ele mesmo.
3. **Citação por fato**: "only cite a source for a fact it actually contains" (reforço explícito,
   já existia instrução parecida, mas sem o "actually contains"). Ataca (e).
4. **Contexto por seção, não só o chunk retornado pela busca**: `_section_text` (novo, calculado
   uma vez no `__init__`) junta todos os chunks que compartilham `(url, section)` antes de aplicar
   `focused_excerpt`. A busca (ranking, Bloco 2) não mudou — só o texto que a geração vê para os
   chunks já escolhidos ficou mais completo, sem aumentar o número de chamadas. Ataca (b)/(c) —
   q06 do Bloco 1 tinha a condição de faturamento cortada por `EVIDENCE_PROMPT_CHARS=700`; com o
   texto completo da seção disponível, `focused_excerpt` tem mais chance de incluir a frase certa.

**Decomposição explícita de perguntas compostas (sub-perguntas separadas) não foi implementada** —
a instrução de completude (item 1) foi testada primeiro por ser muito mais simples, e já melhorou a
cobertura o suficiente para não justificar o custo extra de uma segunda rodada de busca por
sub-pergunta nesta iteração. Fica como item aberto se precisar de mais uma rodada.

**Comparação Haiku × Sonnet para a redação do Knowledge: não testada** — faltou tempo/orçamento
nesta rodada; prioridade foi medir o que já está implementado. Item aberto.

## Resultado (dev, antes → depois, mesmo juiz, mesma amostra)

| Métrica | antes | depois |
|---|---|---|
| coverage_mean | 0,681 | 0,708 |
| full_coverage_rate | 0,667 | 0,694 |
| numbers_supported_rate | 0,973 | **1,000** |
| citation_correct_rate | 0,696 | **0,833** |
| abstention_correct_rate | 1,000 | 1,000 |
| judge_correct_rate | 0,650 | 0,650 |
| judge_grounded_rate | 0,775 | 0,850 |
| judge_usefulness_mean | 3,80 | 3,65 |
| latência média | 8,73 s | 7,89 s |

(`citation_correct_rate` e `abstention_correct_rate` na coluna "antes" já estão recalculados com o
conserto do Bloco 3b abaixo, para comparação justa.)

Ganho real em fundamentação e citação; `judge_correct_rate` não mudou e `usefulness` caiu um pouco
— hipótese: a instrução "siga a evidência, nunca sua suposição" torna a resposta mais cautelosa em
alguns casos, trocando um pouco de utilidade percebida por mais fundamentação. É uma troca
defensável dado que (c) contradizer a evidência foi a causa mais grave do Bloco 1 (q26: a resposta
contradisse um fato explícito da própria evidência citada).

## Confirmação única (test congelado e `quality_test_v2`)

| Métrica | test (23) | quality_test_v2 (66, novo) |
|---|---|---|
| coverage_mean | 0,810 | 0,647 |
| citation_correct_rate | 0,917 | 0,843 |
| numbers_supported_rate | 0,952 | 0,985 |
| judge_correct_rate | 0,652 | **0,758** |
| judge_grounded_rate | 0,870 | 0,894 |
| abstention_correct_rate | 0,500 | — (sem itens de abstenção) |
| custo/pergunta | US$ 0,0011 | US$ 0,0010 |

`quality_test_v2` nunca foi usado para ajustar nada (nem o prompt, nem o conjunto) — é a medição
mais honesta desta rodada, e `judge_correct_rate=0,758` é o melhor número já visto no projeto para
"correto" segundo o juiz, numa amostra adversarialmente nova.

## Bloco 3b — dois bugs do próprio medidor, encontrados ao medir (não do produto)

1. **Regex de abstenção perdia uma paráfrase válida**: `ABSTAIN_TEXT` em `run_answer_quality.py`
   não reconhecia "não é possível informar/confirmar/responder/determinar", só "não
   tenho/encontrei/há/consta/consigo confirmar/posso informar". O item `a04` do dev recusou
   corretamente ("Não é possível informar a taxa Selic...") mas `abstention_correct` deu `False`
   só por causa da frase. Ampliado o regex para cobrir a paráfrase (generalizado, não a frase
   específica do item). `a02` do test (recusa de telefone pessoal de gerente, por privacidade, não
   por falta de evidência) continua sem bater com o regex — é uma categoria de recusa diferente
   ("não posso fornecer dado de terceiro" vs. "não encontrei evidência"), fora do que esse regex
   tenta cobrir; documentado, não corrigido (mesmo padrão já registrado antes para a03–a05).
2. **Evidência e `tool_data` armazenados cortados em 6 itens, mas os checks e o juiz usavam a
   lista completa** (até 8, em perguntas `multi_intent` que combinam 2 especialistas): uma citação
   válida `[7]` ou `[8]` ficava fora do que `--rescore`/`--rejudge` conseguem verificar, porque o
   JSON salvo só tinha 6. Corrigido: `run_answer_quality.py` agora guarda a lista completa; o
   `judge()` em `answer_quality.py` também via só 6 evidências mesmo na rodada ao vivo — aumentado
   para 8, igual ao `MAX_EVIDENCE_ITEMS` do Critic. Achado no item `m01` ao comparar
   `--rescore` com o run original (`citation_correct` mudava de `True` para `False` sem nenhuma
   mudança de código — sinal de que algo estava inconsistente). Os relatórios `quality_dev_baseline`
   e `quality_dev_block3` (não commitados, só em scratch) ainda têm evidência de 6 itens porque
   foram gerados antes do conserto; o `test` e o `quality_test_v2` commitados já usam a correção.

## Itens honestamente não resolvidos

- Decomposição explícita de perguntas compostas: não implementada.
- Haiku × Sonnet na redação do Knowledge: não comparado.
- Meta "corretas≥90%, fundamentadas≥95%, citações≥95%, números≥98%" no `quality_test_v2`: parcial
  — citações 0,843 (perto), números 0,985 (perto), fundamentadas (grounded) 0,894 (perto),
  corretas pelo juiz 0,758 (abaixo de 0,90). Progresso real, meta não batida.
