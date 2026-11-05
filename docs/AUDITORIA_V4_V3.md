# Auditoria V4 × feedback v3

Cada gap/desconto do feedback v3 sobre `c287c00` (nota 8,2/10) → o que foi feito nesta missão
(V8) → status → evidência. Ver `docs/CHECKLIST_V8.md` para o detalhe por bloco.

| Dimensão v3 | Nota v3 | Gap citado | Bloco | Status | Evidência |
|---|---|---|---|---|---|
| RAG | 7,3 | "a busca" é um dos três fatores que separam dos finalistas | 2 | PARCIAL | recall@3 0,619→0,762 no test congelado (reranker por LLM); meta 0,90 não atingida — `docs/RELATORIO_BUSCA_2026-11-05.md` |
| Julgamento | 8,3 | "validação humana do juiz" (κ≈0 com 1 rotulador só) | 4 | PARCIAL | guia + ferramenta + 105 itens prontos; κ real depende do segundo rotulador (bloqueado) — `docs/evaluation/GUIA_ROTULAGEM.md` |
| Business/Julgamento | — | "qualidade das respostas (71% corretas)" é o fator nº1 | 1, 3 | PARCIAL | causas classificadas (18/63, Bloco 1); geração melhorada (citação 0,70→0,83 no dev, juiz 0,76 no quality_test_v2) — `docs/RELATORIO_GERACAO_2026-11-05.md` |
| Orquestração | 8,5 | "a cadeia continua pesada"; ablação não mostrava se cada peça se paga | 5, 6 | RESOLVIDO (medido; decisão foi manter tudo) | `docs/RELATORIO_ABLACAO_2026-11-05.md`: remover PolicyGate = 19/19 falsos negativos; remover Context Intelligence = -9,1 p.p. de qualidade E mais lento/caro; remover Critic = -4,5 p.p. de qualidade. 1 rodada (não 3), sinal grande e unidirecional em todas |
| Simplicidade | — (João é superior) | arquitetura mais simples que a nossa | 6 | RESOLVIDO — decisão: **não simplificar**, com números | Nenhuma remoção testada economizou o suficiente para compensar a perda de qualidade/segurança; CI e PolicyGate não foram fundidos por serem redes de segurança independentes — `docs/RELATORIO_ABLACAO_2026-11-05.md` |
| Memória | 8,0 | "uma rodada; o avaliador por palavra-chave infla os acertos sem memória" | 9 | PARCIAL — medido, meta não atingida | 12→30 conversas, juiz LLM somado à palavra-chave: recall 70–77% com memória vs. 0–7% sem (meta 93%); bug de token de auth e padrão "sabe mas nega" encontrados e parcialmente corrigidos — `docs/RELATORIO_MEMORIA_2026-11-05.md` |
| HITL | 8,0 | "Telegram implementado, mas sem validação com token real"; "sem quatro olhos nem SLA" | 7 | NÃO — depende do usuário (token) e é o maior item de engenharia ainda aberto | token pedido ao usuário em 2026-11-05; quatro olhos e SLA não implementados (greenfield, fora da prioridade 1→2→3→4→6 da missão quando o tempo aperta) |
| Produção | 8,0 | SQLite como estado; HMAC próprio sem JWKS/rotação; chave de operador compartilhada | 8 | NÃO | fora da prioridade 1→2→3→4→6; escopo grande (Postgres+Alembic, JWT+JWKS, operadores individuais) não iniciado nesta rodada |
| Avaliação | 8,3 | gate Semantic Quality "parcial" | 4, 10 | PENDENTE | depende da calibração humana (Bloco 4) |
| Segurança | 8,0 | (sem gap específico citado na v3 para este ciclo) | — | — | — |
| Tools | 8,7 | (sem gap específico citado na v3 para este ciclo) | — | — | — |
| Observabilidade | 8,8 | (sem gap específico citado na v3 para este ciclo) | — | — | — |

## Perguntas de entrevista da v3

1. **"Quais são os principais modos de falha nos 29% restantes?"** Respondida no Bloco 1:
   geração (contexto certo, resposta errou/omitiu/contradisse) é a causa dominante (6/18, 33%),
   seguida de completude de pergunta composta (3/18) e citação para trecho errado (3/18); erro do
   próprio juiz/rubrica responde por 3/18 (17% dos "erros"); busca/roteamento não apareceram como
   causa nesta amostra de 18 casos. Ver `docs/ANALISE_ERROS_2026-11-05.md`.
2. **"Em qual sinal confiar em produção (Critic, juiz ou humanos)?"** Pendente — depende da
   calibração humana do Bloco 4 (κ humano×humano, depois juiz×humanos e Critic×humanos), que
   depende do segundo rotulador.
3. **"Reranker, chunking ou expansão de consulta?"** Respondida no Bloco 2: reranker por LLM
   (Haiku) venceu com ganho real e custo baixo (~US$0,0002/pergunta); expansão de sinônimos
   piorou (medido e revertido); chunking por seção/página teve ganho pequeno e inconsistente, não
   adotado nesta rodada. Ver `docs/RELATORIO_BUSCA_2026-11-05.md`.
4. **"A cadeia continua pesada?"** Respondida no Bloco 6: sim, continua sendo uma cadeia de vários
   passos, mas agora medida — cada passo (PolicyGate, Context Intelligence, Critic, fast-path vs.
   planejamento) perde qualidade e/ou segurança mensurável quando removido, e nenhuma remoção
   testada economizou o suficiente para compensar. O pior custo medido foi US$0,0016/pergunta
   (forçar sempre o loop de planejamento). "Pesada" não é o mesmo que "sem justificativa" — o peso
   agora tem números por trás. Ver `docs/RELATORIO_ABLACAO_2026-11-05.md`.
5. **"Migração e operador com réplicas?"** Não respondida nesta rodada (Bloco 8 não iniciado,
   fora da prioridade quando o tempo aperta).

## O que ainda falta, sem rodeio

- Blocos 5 e 6 medidos com **1 rodada**, não as 3 pedidas pela missão (custo/tempo) — sinal grande
  e unidirecional em todas as comparações, documentado como limitação em
  `docs/RELATORIO_ABLACAO_2026-11-05.md`.
- Bloco 9 (memória) medido em **2 rodadas**, não 3 — meta de 93% não atingida (ficou em 70-77%);
  dois bugs reais encontrados e um deles (token de autenticação do script de avaliação) totalmente
  corrigido, o outro (modelo nega um fato que ele mesmo recuperou) só parcialmente — detalhe em
  `docs/RELATORIO_MEMORIA_2026-11-05.md`.
- Calibração humana real do Bloco 4 — bloqueada no segundo rotulador.
- Blocos 7 (Telegram quatro-olhos/SLA) e 8 (Postgres/JWT/operadores) não iniciados — maior risco
  de nota, documentado como tal, não escondido.
