# CHECKLIST V8 — de 8,2 para 9,5+ (feedback v3)

Fonte: `docs/MISSAO_V8.md`. Feedback v3 sobre `c287c00`: **8,2/10**. Notas por dimensão: Business 8,3 ·
Orquestração 8,5 · RAG **7,3** · Tools 8,7 · Segurança 8,0 · Memória 8,0 · HITL 8,0 · Avaliação 8,3 ·
Observabilidade 8,8 · Produção 8,0 · Julgamento 8,3. Gate Semantic Quality: **parcial**.

Cada linha: gap/desconto → bloco que resolve → status (RESOLVIDO / PARCIAL / NÃO) → evidência.
Commit por bloco, sem alterar expectativas de teste/eval para passar.

## Bloco 0 — Regra anti-sobreajuste (pré-requisito de todos os blocos)

| # | Item | Status | Evidência |
|---|---|---|---|
| 0.1 | Separar `answer_quality.jsonl` (63) em dev (40) / test (23) | RESOLVIDO | `answer_quality_dev.jsonl`, `answer_quality_test.jsonl`, seed 20261105, `backend/app/evaluation/DATASETS.md` |
| 0.2 | Separar `retrieval_questions.json` (70) em dev (45) / test (25) | RESOLVIDO | `retrieval_questions_dev.json`, `retrieval_questions_test.json` |
| 0.3 | Criar `quality_test_v2` (≥60) nunca usado para ajuste | RESOLVIDO | `backend/app/evaluation/quality_test_v2.jsonl` (66 itens, origem documentada) |
| 0.4 | Criar `retrieval_test_v2` (≥60) nunca usado para ajuste | RESOLVIDO | `backend/app/evaluation/retrieval_test_v2.json` (66 itens) |
| 0.5 | Teste anti-vazamento dos conjuntos novos | RESOLVIDO | `backend/tests/test_dataset_splits.py` (5 testes, todos verdes) |
| 0.6 | `run_answer_quality.py` / `run_retrieval_eval.py` aceitam `--dataset` | RESOLVIDO | flag `--dataset` adicionada a ambos |

## Bloco 1 — Análise de erro (base de tudo)

| # | Item | Status | Evidência |
|---|---|---|---|
| 1.1 | Classificar causa raiz dos 29% incorretos/não fundamentados/citação errada da v3 (a–h) | RESOLVIDO | `docs/ANALISE_ERROS_2026-11-05.md`: 18/63 itens (28,6%) de `ANSWER_QUALITY_cloud_2026-11-05.json` (ecebfa7, mesmo run que gerou os números da v3), causa por item |
| 1.2 | `docs/ANALISE_ERROS_<data>.md` com contagem por causa e plano | RESOLVIDO | (c) geração 6, (d) composta 3, (e) citação 3, (h) juiz 3, (g) dado desatualizado 2, (b) truncado 1, (a)/(f) 0 — plano prioriza Bloco 3, depois Bloco 4, depois Bloco 2 |

## Bloco 2 — Busca: Recall@3 0,70 → ≥0,90

| # | Item | Status | Evidência |
|---|---|---|---|
| 2.1 | Medir baseline no `retrieval_questions_dev.json` (recall@3, MRR, abstenção) | RESOLVIDO | `docs/RELATORIO_BUSCA_2026-11-05.md`: recall@3=0,744, MRR=0,612; achado: hybrid==bm25 exato (denso não agrega nesta amostra) |
| 2.2 | Reranker cross-encoder (ou LLM) sobre top-10 do híbrido — medir qualidade/latência/custo | RESOLVIDO (LLM, não cross-encoder local) | `KnowledgeAgent.retrieve(mode="hybrid_rerank")`; test recall@3 0,619→0,762, MRR 0,599→0,675, US$0,0002/pergunta; cross-encoder local descartado por risco de RAM (~1,2GB livre) |
| 2.3 | Chunking: tamanho/overlap, chunk por seção com breadcrumb, parent document | PARCIAL (testado, não adotado) | Parent document por seção: recall@3 0,744→0,769; por página: recall@1 0,487→0,590; não supera o reranker isolado nem combina melhor — não adotado nesta rodada |
| 2.4 | Expansão/reescrita de consulta (multi-query, sinônimos pt/en do vocabulário do site) | PARCIAL (testado, rejeitado) | Sinônimos de domínio pioraram recall@3 (0,744→0,692); revertido antes do commit, negativo documentado |
| 2.5 | Ajustes de fusão BM25/denso (RRF), filtros por idioma/seção, boost de título | NÃO | título/idioma já existiam antes da V8; RRF não testado por tempo |
| 2.6 | Diagnosticar os itens "sem o fato por falha de busca" e abstenções do modo denso | RESOLVIDO | 5/39 perguntas respondíveis do dev (r04,r25,r38,r40,r59) não têm a URL certa nem no pool de 10 — precisa de pool maior ou melhor recall de 1ª linha, não de reranking |
| 2.7 | Meta no `test`: recall@3≥0,90, MRR≥0,80, abstenção correta 100%, latência reportada | PARCIAL — não atingida | test: recall@3=0,762 (meta 0,90), MRR=0,675 (meta 0,80); abstenção fora-da-base=100% nos 3 splits; latência extra ~1,5s/pergunta, tudo documentado em `docs/RELATORIO_BUSCA_2026-11-05.md` |

## Bloco 3 — Geração: corretas ≥90%, fundamentadas ≥95%

| # | Item | Status | Evidência |
|---|---|---|---|
| 3.1 | Prompt do Knowledge: completude, números/condições obrigatórios, citação por afirmação | RESOLVIDO | `docs/RELATORIO_GERACAO_2026-11-05.md`: citação 0,696→0,833 no dev (mesma amostra, antes/depois) |
| 3.2 | Contexto com seção inteira dos melhores chunks (parent document), ordenado por relevância | RESOLVIDO (só no contexto de geração, não na busca) | `_section_text` em `knowledge_agent.py`; junta chunks da mesma `(url,section)` antes do `focused_excerpt` |
| 3.3 | Verificação pós-geração pelo Critic por sentença, com reescrita única guiada | RESOLVIDO (já existia antes da V8) | `supervisor/replanner.py::_replan_after_rejection` — reescrita única com os issues do Critic como feedback, pré-existente; não é por sentença, é por resposta |
| 3.4 | Decomposição de perguntas compostas (cobrir todas as partes) | NÃO (instrução de completude usada em vez disso) | ver 3.1; decomposição de fato não implementada |
| 3.5 | Comparar `claude-haiku-5-5` × `claude-sonnet-5-5` na redação do Knowledge (custo/latência) | NÃO | não testado por tempo |
| 3.6 | Meta no `quality_test_v2`: corretas≥90%, fundamentadas≥95%, citações≥95%, números≥98% | PARCIAL — não atingida | quality_test_v2: corretas(juiz)=0,758, fundamentadas=0,894, citações=0,843, números=0,985 — todas melhoraram, nenhuma bateu a meta |

## Bloco 4 — Validação humana do juiz e do Critic (Gate Semantic Quality)

| # | Item | Status | Evidência |
|---|---|---|---|
| 4.1 | Guia de rotulagem objetivo (fundamentação × completude), com evidência visível | RESOLVIDO | `docs/evaluation/GUIA_ROTULAGEM.md`: duas perguntas separadas, exemplos de cada nota, regra sobre menus/dados sintéticos |
| 4.2 | Segundo rotulador humano independente — **depende do usuário** | BLOQUEADO (pedido ao usuário em 2026-11-05; ferramenta e guia agora prontos) | ver estimativa de tempo abaixo |
| 4.3 | ≥100 itens rotulados (reais + defeitos injetados), calibração/teste separados | PARCIAL — itens prontos, rotulagem pendente | `docs/evaluation/labeling_items.jsonl`: 105 itens (85 respostas reais do sistema atual, pós-Bloco 2/3, + 20 defeitos injetados) |
| 4.4 | Medir κ humano×humano, depois juiz×humanos e Critic×humanos no teste | PARCIAL — infraestrutura pronta, falta rodar | `calibrate_critic.py::human_human_kappa` (testado com dados sintéticos, `tests/test_calibrate_critic.py`, 6 casos); `label_cli.py` agora grava um arquivo por rotulador (`human_labels_<nome>.jsonl`) para nunca verem o rótulo um do outro |
| 4.5 | Recalibrar juiz e Critic só com a parte de calibração | NÃO — depende de 4.2–4.4 | — |
| 4.6 | Meta κ≥0,6 (humano×humano e juiz×humanos); se não atingir, publicar negativo como na v3 | NÃO — depende de 4.2–4.4 | — |
| 4.7 | Resposta à pergunta 2 da entrevista (em qual sinal confiar em produção) | NÃO — depende de 4.2–4.4 | — |

**Estimativa de tempo para a rotulagem** (105 itens, ~45-90s cada com as duas perguntas + motivo
opcional): ~1h20 a 2h40 por rotulador. Pode ser feito em partes — o CLI retoma de onde parou
(`python -m app.evaluation.label_cli --labeler <nome>`). Sugestão: primeiro ~20-25 itens como
calibração (mede κ humano×humano antes de seguir), depois o restante.

## Bloco 5 — Replanejamento com tráfego real

| # | Item | Status | Evidência |
|---|---|---|---|
| 5.1 | Critic ligado × desligado no `quality_test_v2` + benchmark, 3 rodadas | NÃO | — |
| 5.2 | Taxa de reprovação natural, % corrigido, variação de corretas/fundamentadas, custo extra | NÃO | — |
| 5.3 | Conclusão documentada: o Critic se paga em respostas reais? | NÃO | — |

## Bloco 6 — Simplificar a arquitetura com dados

| # | Item | Status | Evidência |
|---|---|---|---|
| 6.1 | Ablação no `quality_test_v2` + heldout de contexto + safety set, 3 rodadas, por componente | NÃO | — |
| 6.2 | Decisão com números: fundir Risk+PolicyGate / CI+rota, remover o que não se paga | NÃO | — |
| 6.3 | Diagrama simplificado no README + justificativa numérica + resposta à pergunta 4 | NÃO | — |

## Bloco 7 — Telegram real e HITL operacional

| # | Item | Status | Evidência |
|---|---|---|---|
| 7.1 | Token do bot + chat de operadores — **depende do usuário** | BLOQUEADO (pedido ao usuário em 2026-11-05, instruído a colocar direto no `.env`) | — |
| 7.2 | Validar fluxo completo com Telegram real (card → assumir → responder → cliente vê → resolver) | NÃO | — |
| 7.3 | Evidência: prints + trace em `docs/evidence/hitl/telegram/` | NÃO | — |
| 7.4 | Quatro olhos: ação de risco exige segundo aprovador | NÃO | — |
| 7.5 | SLA por prioridade + alerta (Prometheus/Grafana + Telegram) + escalonamento + métricas | NÃO | — |

## Bloco 8 — Estado e identidade de produção

| # | Item | Status | Evidência |
|---|---|---|---|
| 8.1 | Postgres como estado padrão (compose produção), Alembic, migração de dados, testes nos dois | NÃO | — |
| 8.2 | Claim atômico multi-réplica + eventos ao vivo com 2+ réplicas + worker Telegram com lock | NÃO | — |
| 8.3 | JWT (PyJWT), `kid`, rotação com overlap, JWKS, expiração/revogação, testes de rotação | NÃO | — |
| 8.4 | Operadores individuais (senha com hash, papéis, sessão, auditoria), sem chave compartilhada | NÃO | — |
| 8.5 | Resposta à pergunta 5 da entrevista | NÃO | — |

## Bloco 9 — Memória

| # | Item | Status | Evidência |
|---|---|---|---|
| 9.1 | Avaliador por LLM juiz (rubrica) além de palavra-chave, ≥30 conversas longas, 3 rodadas | NÃO | — |
| 9.2 | Analisar falhas e corrigir (resumo, recuperação de fatos, `recall_conversation`) | NÃO | — |
| 9.3 | Meta ≥28/30 com memória, diferença vs. sem memória medida corretamente | NÃO | — |

## Bloco 10 — Relatório, auditoria v3 e simulação

| # | Item | Status | Evidência |
|---|---|---|---|
| 10.1 | `docs/AUDITORIA_V4_V3.md`: cada gap/desconto v3 → status + evidência | NÃO | — |
| 10.2 | `docs/RESPOSTAS_ENTREVISTA_V3.md` fora do Git | NÃO | — |
| 10.3 | README atualizado (arquitetura simplificada, números dev/test, links de evidência) | NÃO | — |
| 10.4 | `TESTING.md` atualizado; gravações novas para replay do CI; CI local verde; clone limpo | NÃO | — |
| 10.5 | Simulação de avaliação no formato do feedback v3, mesmos pesos | NÃO | — |
| 10.6 | Resumo final + comandos de push; aguardar autorização | NÃO | — |

## Outros gaps identificados por mim (fora da lista explícita da v3)

| # | Item | Status | Evidência |
|---|---|---|---|
| X.1 | `retrieval_test_v2` e `quality_test_v2` usam as mesmas 66 páginas (pergunta igual nos dois arquivos) — aceitável pela missão ("mesma pergunta serve às duas medições"), mas documentar a dependência para não contar como dois sinais independentes | RESOLVIDO (documentado em `DATASETS.md`) | `backend/app/evaluation/DATASETS.md` |
| X.2 | `quality_test_v2` não foi medido nem uma vez ainda (sanity check só confirmou que os `expected_urls` existem via BM25, recall@3=0,94 — esperado, pois a pergunta foi escrita a partir da própria página) | PARCIAL | `retrieval_v2_bm25_sanity` (scratch, não commitado — é só verificação de integridade, não resultado a reportar) |
| X.3 | Carimbo de dataset (`dataset:` no relatório) ausente em runs anteriores a hoje — relatórios antigos (`ANSWER_QUALITY_cloud_2026-11-05.json` etc.) não têm o campo; não retroativo | RESOLVIDO (campo adicionado só para runs novos) | `run_answer_quality.py` |

---

**Prioridade se o tempo/limite apertar** (ordem da missão): Bloco 1 → 2 → 3 → 4 → 6. Blocos 5, 9, 10 depois.
Blocos 7 e 8 são os de maior risco de não fechar (dependem do usuário / maior escopo de engenharia);
qualquer parte não concluída fica como NÃO ou PARCIAL aqui, nunca escondida.
