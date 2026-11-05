# Memória — rodada 3 (05/11/2026, pós-publicação): roteamento de perguntas de recuperação

Continuação do Bloco 9: a causa (A)/(B) identificada nas rodadas 1-2 ("um menu de esclarecimento
intercepta a pergunta de recuperação antes de qualquer especialista tentar lembrar") — a mais
arriscada de tocar, porque fica no mesmo prompt da Context Intelligence calibrado com cuidado nos
Blocos 1/4/6 para segurança.

## Diagnóstico

Perguntas como "Which days did I say we are open?" ou "Qual o nome do meu principal fornecedor que
eu mencionei?" não citam nenhum produto Getnet — a regra (6) do prompt da CI ("a vague message with
no clear topic needs clarification") classificava esse tipo de pergunta como vaga, caindo no menu
de esclarecimento em vez de ir para o Knowledge (que tem a ferramenta `recall_conversation`).

## Correção

Adicionei uma nova regra geral (9) ao prompt da Context Intelligence
(`app/agents/context_intelligence.py`): uma pergunta pedindo para lembrar/repetir/confirmar algo
que o próprio cliente disse antes não é vaga, mesmo sem citar produto — deve ir para o
`knowledge_specialist` com baixa ambiguidade. Regra geral, sem nenhuma frase copiada de cenário de
avaliação (mesma disciplina do Bloco 1).

## Verificação

1. **Segurança/roteamento** (`context_scenarios_heldout_v2`, 109 casos) — **idêntico à base do
   Bloco 6**: 0/19 falsos negativos, recall crítico 1,00, falso positivo 2,44%, acerto de rota
   0,9565 (66/69), os mesmos 3 erros de rota de antes (`h2-014`, `h2-038`, `h2-065`). **Nenhuma
   regressão de segurança ou roteamento.**
2. **Casos de recuperação visados** (3 testados diretamente, os mesmos padrões que falharam nas
   rodadas 1-2 do Bloco 9):
   - "Which days did I say we are open?" → antes: menu de esclarecimento. Depois:
     `context_directed_dispatch` direto pro Knowledge, resposta correta com citação.
   - "What is the name of my shop that I told you at the start?" → mesma melhora: despacho direto,
     resposta correta.
   - "Qual o nome do meu principal fornecedor que eu mencionei?" → **ainda falha**, mas por uma
     causa diferente e pré-existente: a Context Intelligence classifica `risk_level=ambiguous`
     (confiança 0,60) para essa frase **mesmo sem nenhuma mudança de código** (testei revertendo a
     regra 9 e o problema persiste idêntico) — não é uma falha de roteamento por "pergunta vaga",
     é a classificação de risco retornando ambíguo para uma frase sem nenhuma palavra de perigo.
     **Bug novo, separado, não corrigido aqui** (foge do escopo desta correção e tocaria a
     calibração de risco/confiança da CI de forma mais ampla — precisa de investigação própria).

## Decisão

**Adotada.** 2 dos 3 padrões de recuperação testados melhoram de "menu de esclarecimento" para
resposta correta e direta; o terceiro continua falhando por um motivo diferente e já existia antes
desta mudança (não é uma regressão introduzida por ela). Segurança e roteamento no heldout de 109
casos ficaram bit a bit idênticos à base — risco de regressão descartado com medição, não por
confiança.

## Achado novo para a próxima rodada

A Context Intelligence classifica `risk_level=ambiguous`/confiança 0,60 para algumas frases
completamente benignas em português (ex.: "Meu principal fornecedor se chama Distribuidora Vale
Verde" — a frase que *fornece* a informação, não só a que pergunta por ela, já recebe essa
classificação). Isso sugere um problema de calibração de confiança mais amplo do classificador de
contexto em português, não restrito a perguntas de recuperação de memória — vale investigar
separadamente, com uma amostra maior de frases benignas em pt, antes de qualquer ajuste.
