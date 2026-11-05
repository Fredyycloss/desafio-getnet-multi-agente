# Análise de erro — V8 Bloco 1

Fonte: `docs/eval/ANSWER_QUALITY_cloud_2026-11-05.json` (commit `ecebfa7`, `claude-haiku-5-5` gerando,
`claude-sonnet-5-5` julgando, 63 itens do `answer_quality.jsonl` completo — ainda não existia o split
dev/test). Seus agregados (`judge_correct_rate=0.7143`, `judge_grounded_rate=0.7937`,
`citation_correct_rate=0.8378`) **são exatamente** os números citados pelo feedback v3 (71,4% corretas,
79,4% fundamentadas, 83,8% citações corretas), então este é o run que o avaliador viu. Não é o run
contaminado pelo bug do `DEMO_TODAY` (esse ficou isolado em `docs/eval/answer_quality_runs/1_with_demo_today_after_midnight.json`
e não é este arquivo).

18 dos 63 itens (28,6% — bate com "29% restantes" da v3) foram julgados `partially_correct`, `incorrect` ou
tiveram `citations_correct=False`. Cada um foi reclassificado abaixo com a causa raiz, usando o `trace`
completo do item (evidência, checks determinísticos e `unsupported_claims` do juiz).

## Metodologia

Para cada item: li a pergunta, a resposta, as evidências (`evidence`, `sources`) e o veredito do juiz com
os `unsupported_claims`. A causa é a explicação mais direta do defeito, não a mais confortável — quando o
próprio juiz exigiu algo que a resposta não tinha como saber (por não ser um fato, e sim um artefato da
rubrica), isso conta como (h), não como defeito do produto.

## Classificação por causa

| Causa | Itens | Contagem |
|---|---|---|
| (c) contexto certo, geração omitiu/errou o fato | q23, q26, q37, c06, w04, m02 | 6 |
| (d) resposta incompleta por pergunta composta | q13, q28, m01 | 3 |
| (e) citação para trecho/fonte errada | q12, q31, w03 | 3 |
| (h) erro do juiz ou do rótulo (rubrica mal aplicada) | q25, a01, a02 | 3 |
| (g) dado desatualizado/ambíguo no site ou na API | q08, w01 | 2 |
| (b) chunk certo ficou fora do contexto (truncado) | q06 | 1 |
| (a) busca não trouxe a página certa | — | 0 |
| (f) rota/especialista errado | — | 0 |

**18 = 6+3+3+3+2+1.** Nenhum dos 18 casos foi um erro de busca de página (a) ou de roteamento (f) — a
página certa sempre chegou ao Knowledge e o especialista certo foi escolhido. O problema concentrado é
**geração**: a resposta tinha a evidência certa na mão e, ainda assim, omitiu um fato, inventou um detalhe
não presente, contradisse a evidência, ou citou o trecho errado para sustentar uma afirmação. Em segundo
lugar, **completude de pergunta composta**. Em terceiro, **o próprio juiz**: 3/18 (17% dos "erros", 4,8% do
total) são a rubrica de fundamentação sendo aplicada a texto de menu/esclarecimento ou dando veredito
pior sem nenhuma `unsupported_claims` — sinal de que o Bloco 4 (calibração humana) tem razão de ser.

Isso não invalida o Bloco 2 (busca): o `retrieval_questions.json` dedicado mede recall@3≈0,70 com perguntas
mais difíceis que as do `answer_quality.jsonl` (a maioria das perguntas de qualidade foi escrita a partir de
uma página que a busca BM25/híbrida já encontra fácil). As duas métricas medem coisas diferentes e os dois
blocos continuam necessários — mas **nesta amostra específica de 63 respostas**, a geração é o gargalo, não
a busca.

## Exemplos (evidência do trace)

**q26 — (c), o mais grave.** Pergunta sobre quando o valor do empréstimo com garantia de recebíveis cai na
conta. A evidência [1] diz literalmente "O valor é creditado na sua Get Conta no mesmo dia". A resposta
afirmou que o material "não informa o momento exato" e que isso "não pode ser confirmado para todos os
clientes" — contradizendo a evidência citada pela própria resposta. `numbers_correct=False`,
`grounded=False`, 5 `unsupported_claims` do juiz, todas apontando a mesma contradição.

**m02 — (c).** A evidência diz "Receba os pagamentos em tempo real, sem espera" sobre Pix; a resposta disse
que "não pôde confirmar se o Pix é instantâneo" e que "pode depender do contrato" — o oposto do que a fonte
citada afirma.

**q13 — (d).** Pergunta composta sobre o Link de Pagamento perguntando por débito e crédito; a resposta
cobriu só uma modalidade (`coverage=0,33`, faltando "débito" e "crédito" como fatos distintos).
`grounded=True` — a parte que respondeu estava certa, só não respondeu tudo.

**q12 — (e).** A resposta recomenda a Central de Atendimento para "taxas de juros específicas", citando um
trecho que na verdade fala da taxa MDR/desconto do contrato, não de juros de parcelamento — citação para o
fato errado dentro do próprio excerto certo.

**q31 — (e), o mais estranho.** A resposta inventa um título de página ("Maquininha POS 3G + Wi-Fi") para a
evidência [2], que na realidade só contém "Dúvidas sobre as maquininhas?" e texto de FAQ da Get Lite — uma
alucinação sobre a própria fonte, não sobre o conteúdo.

**a01/a02 — (h).** São o menu de esclarecimento determinístico para pedido de atendimento humano (texto de
protocolo). O juiz marcou `unsupported_claims` dizendo que "a escolha por atendimento humano abre um
protocolo na fila de atendentes" não está fundamentada em evidência — mas esse texto é um menu de produto,
não uma afirmação factual sobre o site, e a regra do CLAUDE.md permite texto fixo aqui (menu de
esclarecimento). A rubrica do juiz (`grounded` contra `evidence`) não tem categoria para esse caso.

**q06 — (b).** `missing_facts=['2.000']`; o juiz aponta que o excerto [2] está truncado antes da condição
relevante. `EVIDENCE_PROMPT_CHARS=700` cortou a frase com a faixa de faturamento antes do fato citável.

## Plano — cada bloco seguinte ataca por ordem de frequência

1. **Bloco 3 (geração, causas c+d+e = 12/18, 67%)** é a maior prioridade de ganho nesta amostra:
   completude obrigatória para pergunta composta (ataca d), verificação pós-geração sentença-a-sentença
   contra a evidência citada (ataca c — pegaria q26 e m02 na hora: a contradição é literal), e exigir que
   cada citação aponte o trecho exato que sustenta a afirmação, não só a fonte certa (ataca e — q12, q31).
2. **Bloco 4 (calibração do juiz, causa h = 3/18, 17%)**: o guia de rotulagem precisa dizer explicitamente
   que texto de menu/esclarecimento determinístico não é avaliado pela rubrica de fundamentação do
   `answers_question`/`grounded` — ou o juiz continuará penalizando um comportamento correto do produto.
3. **Bloco 2 (busca, causas a+b = 1/18, 6% nesta amostra)**: baixo nesta amostra específica, mas o
   `retrieval_questions.json` mede recall@3≈0,70 separadamente com perguntas mais difíceis — o bloco segue
   necessário, só não é o que explica a maioria dos 18 casos aqui. Ajustar `EVIDENCE_PROMPT_CHARS`/parent
   document ajudaria o caso (b) (q06).
4. **(g), dado desatualizado/ambíguo (2/18)**: fora do nosso controle (conteúdo do site, frescor da API de
   câmbio) — não há bloco de código que resolva isso; é um limite de qualidade de fonte, documentar como tal.
5. **c06 já tem a causa corrigida** no bloco anterior (prompt do writer no commit `16998c3`, antes desta
   missão V8 começar) — fica registrado aqui como exemplo de (c), mas não é um item aberto.
