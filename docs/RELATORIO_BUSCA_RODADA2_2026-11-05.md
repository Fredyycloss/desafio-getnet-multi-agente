# Busca — rodada 2 (05/11/2026, pós-publicação)

Continuação do Bloco 2 depois de fechar a missão V8: tentar fechar a meta de recall@3≥0,90 que
ficou em 0,762 no `test`. Duas hipóteses testadas no `dev` (45 perguntas), as duas **negativas ou
marginais**, nenhuma adotada por padrão.

## 1. Aumentar o pool do reranker (10 → 20)

Diagnóstico: 6 das 45 perguntas do dev têm o documento certo fora até do top-20 da pontuação
híbrida atual (rank 12 a 495) — ou seja, aumentar o pool de 10 para 20 só poderia recuperar as que
estão entre 10 e 20 (r04 rank 12, r40 rank 17 na análise aproximada). Medido de verdade:

| Pool | recall@3 | recall@5 | MRR | `answer_rate_in_base` |
|---|---|---|---|---|
| 10 (atual) | 0,795 | 0,821 | 0,703 | 0,872 |
| 20 | 0,769 | 0,769 | 0,705 | 0,872 |

**Piorou**, não melhorou — `answer_rate_in_base` ficou idêntico (34/39 nas duas), confirmando que
nenhum documento adicional foi de fato recuperado; os 20 candidatos só deram ao reranker mais
passagens parecidas-mas-erradas para confundir a ordenação. **Revertido para 10.**

## 2. Reescrita de consulta por LLM (uma chamada extra, keywords de busca)

Diagnóstico mais profundo: para "Quando recebo o dinheiro das minhas vendas?" a melhor posição de
um documento esperado é a 122ª (de 332) tanto na pontuação léxica quanto na densa — um problema de
vocabulário real (o site usa "prazo de recebimento"/"antecipação", não "receber dinheiro"), não de
profundidade de pool.

Testei uma chamada extra ao Haiku que adiciona 3-6 palavras-chave de busca à consulta antes do
embedding. Duas variantes:

| Variante | recall@3 | recall@5 | MRR | `answer_rate_in_base` | latência média |
|---|---|---|---|---|---|
| sem reescrita (atual) | 0,795 | 0,821 | 0,703 | 0,872 | 1,10s |
| reescrita no BM25 **e** denso | 0,872 | 0,872 | 0,761 | **0,410** | 2,11s |
| reescrita só no denso | 0,795 | 0,821 | 0,729 | 0,872 | 2,12s |

A primeira variante parecia ótima no recall — até eu notar que `answer_rate_in_base` despencou de
0,87 para 0,41. Causa: `_bm25_max` assume que um documento poderia bater todos os termos da
consulta; expandir a consulta infla esse teto sem inflar a pontuação real de nenhum documento,
achatando a pontuação léxica calibrada e derrubando o limiar de abstenção (`MIN_RELEVANCE`) para
quase tudo. **Corrigido** restringindo a reescrita só ao embedding denso (nunca ao BM25) — essa
segunda variante não quebra a abstenção, mas também não move o recall@3 (0,795 igual), só MRR
(+0,026) e recall@1 (+0,05), a quase 2× o custo e a latência da busca. **Não é ganho suficiente no
indicador que importa (recall@3) para ligar por padrão.**

## Decisão

Nenhuma das duas mudanças virou padrão. `RERANK_POOL_K` e `KNOWLEDGE_QUERY_REWRITE` ficam como
variáveis de ambiente (`.env.example`, `docker-compose.yml`) para experimentos futuros, desligadas
por padrão — o comportamento medido e commitado no Bloco 2 original continua sendo o de produção.
Testes novos em `backend/tests/test_knowledge_rerank.py` (3 casos: desligado por padrão, aplica
quando ligado, cai para a consulta original em caso de erro).

## O que isso ensina sobre o gap restante (recall@3 0,76→0,90)

As duas hipóteses mais fáceis (pool maior, reescrita simples) não fecham a meta porque o problema
não é "profundidade de busca" nem "uma palavra-chave faltando" — é vocabulário genuinamente
distante (o cliente pergunta com as próprias palavras; o site responde com termos de produto). Uma
correção de verdade provavelmente exige uma reescrita mais agressiva (reformular a pergunta inteira
como 2-3 variações e unir os resultados, não só anexar palavras-chave à consulta original) ou
melhorar o conteúdo/indexação das páginas mais afetadas (institucional, liquidação financeira).
Fica como item aberto, não tentado aqui por ser um escopo maior.
