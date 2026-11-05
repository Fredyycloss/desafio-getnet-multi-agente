# Relatório de busca — V8 Bloco 2

Pergunta 3 da entrevista: "reranker, chunking ou expansão de consulta?" Os três foram testados,
separadamente, no `retrieval_questions_dev.json` (45 perguntas, 39 respondíveis + 6 fora da base).
Decisão tomada no `dev`; confirmação única no `retrieval_questions_test.json` (25 perguntas) e no
`retrieval_test_v2.json` (66 perguntas novas).

## Baseline (dev, `snapshot_hybrid`)

recall@1=0,487 · recall@3=0,744 · recall@5=0,769 · MRR=0,612. Achado incidental: `hybrid` e `bm25`
deram **exatamente** o mesmo resultado nesta amostra — o modo denso (nomic-embed-text) sozinho tem
recall@3=0,385, bem abaixo do lexical, e a fusão 0,55·BM25+0,45·denso não muda o top-k quando o
lexical já domina. O componente denso não está quebrado, só não agrega nesta amostra.

## 1. Expansão de consulta (sinônimos pt, gerados do vocabulário do site)

Testado: dicionário de sinônimos do próprio domínio (maquininha/terminal/POS/TPA, antecipação/
recebíveis, crediário/parcelamento, aluguel/mensalidade, etc.), nunca das perguntas de teste,
aplicado como expansão de `expand_query`. **Resultado: piorou** recall@3 de 0,744 para 0,692 no
`snapshot_hybrid` — a expansão dilui a pontuação BM25 ao ampliar a superfície de correspondência
para documentos não relacionados. **Rejeitado**, revertido antes do commit.

## 2. Chunking (parent document)

Testado: mesclar os chunks por `(url, section)` e por `url` inteira (documento-pai), limitando a
3000–3500 caracteres, medindo recall apenas com BM25 (sem custo de reembedding para a decisão).
- Por seção: recall@3 0,744→0,769 (+0,026), recall@5 0,769→0,846 (+0,077), MRR 0,612→0,648.
- Por página inteira: recall@3 sem mudança (0,744), recall@1 melhora bastante (0,487→0,590),
  MRR 0,612→0,683.
- Combinado com o reranker (seção): recall@3=0,769, MRR=0,675 — **não supera** o reranker isolado
  sobre os chunks finos (recall@3=0,795, abaixo). Ganho real, mas pequeno e inconsistente ao
  combinar. **Não adotado nesta rodada** por não superar a opção 3 isoladamente nem combinada; fica
  registrado como próximo passo caso o Bloco 2 precise de mais uma rodada.

## 3. Reranker por LLM (`claude-haiku-5-5`) — adotado

Alternativa escolhida sobre o cross-encoder local: a máquina tem ~1,2 GB de RAM livre com a stack
rodando (i3, 8 GB), e instalar `torch`+`sentence-transformers` para um cross-encoder (mesmo um
menor, ~300–500 MB em RAM de inferência) arriscava instabilidade sem necessidade, já que a missão
permite a alternativa por LLM explicitamente. O Haiku já está configurado e é barato.

Implementação (`KnowledgeAgent.retrieve(mode="hybrid_rerank")`, `backend/app/agents/knowledge_agent.py`):
busca o pool híbrido de até 10 candidatos, uma chamada ao LLM pede a ordem de relevância (JSON de
índices), e as pontuações de relevância do pool são **redistribuídas** na nova ordem (maior
pontuação do pool para quem o LLM colocou em 1º) — sem isso, promover um documento certo mas com
pontuação lexical baixa a 1º lugar podia cair abaixo de `MIN_RELEVANCE` e virar abstenção errada
(bug encontrado e corrigido durante a própria medição: `answer_rate_in_base` caiu de 0,87 para 0,74
antes da correção, voltou a 0,87 depois). Falha do LLM ou resposta não compreendida → mantém a
ordem original (nunca perde evidência).

| Split | recall@1 | recall@3 | recall@5 | MRR | custo/pergunta | latência extra |
|---|---|---|---|---|---|---|
| dev, baseline hybrid | 0,487 | 0,744 | 0,769 | 0,612 | — | — |
| dev, hybrid_rerank | 0,615 | 0,795 | 0,821 | 0,703 | US$ 0,00019 | ~1,3 s |
| **test (congelado)**, baseline hybrid | 0,571 | 0,619 | 0,667 | 0,599 | — | — |
| **test (congelado)**, hybrid_rerank | 0,619 | **0,762** | 0,762 | 0,675 | US$ 0,00021 | ~1,5 s |
| `retrieval_test_v2` (novo, perguntas "fáceis" — escritas a partir da própria página), baseline | 0,848 | 0,939 | 0,970 | 0,897 | — | — |
| `retrieval_test_v2`, hybrid_rerank | 0,788 | 0,939 | 0,970 | 0,869 | US$ 0,00020 | ~1,3 s |

No `test` congelado o ganho é grande e consistente com o `dev` (+0,14 em recall@3). No
`retrieval_test_v2` — perguntas fáceis, a página certa já fica em 1º ou 2º lugar na maioria dos
casos — o reranker não ajuda e piora levemente o recall@1/MRR: quando a busca já está perto do
teto, reordenar por LLM é só ruído. Isso é esperado e documentado, não escondido.

**Decisão:** adotado como padrão automático — ligado quando o provedor é `anthropic` (rápido,
barato, medido), desligado quando é Ollama local (mais lento, não medido como reranker; ligar lá
multiplicaria a já alta latência do Qwen). Variável `KNOWLEDGE_RERANK` força `true`/`false` em
qualquer provedor. Commit inclui testes (`tests/test_knowledge_rerank.py`, 7 casos) cobrindo o
auto-modo, o override e a redistribuição de pontuação.

## 4. Fusão BM25/denso (RRF)

Não testado nesta rodada — o componente denso já mostrou pouca contribuição isolada (item
"Baseline" acima) e o tempo foi priorizado no reranker, que teve o maior ganho medido. Fica como
item aberto do Bloco 2 caso haja uma rodada adicional.

## Meta da missão (recall@3≥0,90, MRR≥0,80 no test, abstenção correta 100%)

**Não atingida.** recall@3 no test foi de 0,619 para 0,762 com o reranker — uma melhora real e
grande, mas abaixo da meta de 0,90. MRR 0,675, abaixo de 0,80. Abstenção correta sobre
fora-da-base permanece 100% nos três splits (dev/test/v2) com e sem reranker — a parte de
segurança/abstenção não regrediu. Diagnóstico dos casos que seguem sem o fato: no `dev`, 5
perguntas respondíveis (`r04, r25, r38, r40, r59`) não têm a URL certa nem nos 10 primeiros
candidatos híbridos — o reranker não pode corrigir isso, só reordenar o que já está no pool; esses
casos precisam de melhor recall de primeira linha (expansão de consulta mais cuidadosa ou um pool
maior que 10), não de reranking.

## Itens honestamente não resolvidos

- Meta de recall@3/MRR não atingida (ver acima).
- RRF/pesos de fusão não testados.
- Cross-encoder local não testado (risco de RAM na máquina de desenvolvimento, não a de produção).
- O pool de candidatos antes do reranking está travado em 10 (limite existente de `retrieve()`);
  um pool maior (ex. 20) poderia recuperar os 5 casos do `dev` citados acima, mas não foi medido.
