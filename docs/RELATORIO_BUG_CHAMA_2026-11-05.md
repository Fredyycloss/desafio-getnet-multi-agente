# Bug de calibração de risco: "se chama" lido como perigo (05/11/2026, pós-publicação)

Investigação do item priorizado: "Context Intelligence classifica `risk_level=ambiguous` com
confiança baixa em frases benignas em português, sem motivo aparente" (achado da rodada 3 do
Bloco 9).

## Caracterização do alcance

Testei as 30 frases de abertura do eval de memória (mistura pt/en, frases de negócio típicas:
"minha loja fica em...", "meu fornecedor se chama...", etc.) direto na Context Intelligence, sem
histórico:

| Idioma | Frases testadas | `risk_level≠safe` |
|---|---|---|
| pt | 18 | 2 (11%) |
| en | 12 | 0 (0%) |

Só português, e só 2 frases específicas: `store_and_model` ("...se chama Doceria Primavera...") e
`supplier_name_pt` ("...se chama Distribuidora Vale Verde."). As outras 16 frases em português,
incluindo outras que também apresentam o nome do negócio ("Aqui é a Renata, sou dona de um pet shop
pequeno"), passam sem problema — a pista era o verbo, não o tema.

## Causa raiz

`RiskAssessmentAgent.DANGER_VOCABULARY` (e `CONCRETE_HAZARD`) usam a regex `chamas?` para pegar
"chama"/"chamas" como seria em "em chamas" (em fogo). Mas em português **"chama" também é a 3ª
pessoa do verbo "chamar"** — "o produto **se chama** X" usa a mesma palavra. A regex, com limite de
palavra (`\b`), não distingue as duas leituras: toda frase que nomeia algo ("minha loja se chama…",
"meu fornecedor se chama…") acendia o sinalizador de "vocabulário de perigo". O código então aplica
o piso conservador (`_apply_deterministic_context_controls`): se há "vocabulário de perigo" e o
modelo (corretamente) disse `risk=safe` sem marcar linguagem figurada, o código **sobrescreve**
para `risk=ambiguous`, `ambiguity=high`, `clarify=true`, com a razão fixa "Danger vocabulary was
not explained by the model; clarify." — exatamente o texto que eu via no campo `operational_reason`
nas duas frases, confirmando que não era o modelo (nem meu rule 9 do Bloco 9 round 3, que não
mudou nada aqui — tentei e reverti, era hipótese errada) e sim esse piso determinístico no código.

"chamas" no plural (fogo, "em chamas") não colide: a conjugação equivalente de "chamar" na 2ª
pessoa do singular ("tu chamas") é rara ao ponto de ser inexistente no português brasileiro de
atendimento ao cliente usado neste produto.

## Correção

`app/agents/risk_assessment_agent.py`: `chamas?` → `chamas` (sem o `?`, exigindo o plural) nas duas
listas (`CONCRETE_HAZARD` e `DANGER_VOCABULARY`). "Em chamas" continua detectado; "se chama" deixa
de ser lido como perigo.

## Verificação

- Teste novo e permanente em `tests/test_risk_assessment_context.py` (2 casos: nomear algo não é
  perigo; "em chamas" continua sendo). Suite completa: 390/390.
- As mesmas 30 frases: **0/18 pt e 0/12 en** com `risk≠safe` depois da correção (eram 2/18 antes).
- Heldout de segurança/roteamento (109 casos, `context_scenarios_heldout_v2`) **idêntico à base do
  Bloco 6/9**: 0/19 falsos negativos, recall crítico 1,00, falso positivo 2,44%, acerto de rota
  0,9565 — os mesmos 3 erros de rota de sempre. Nenhuma regressão.

## Por que isso importava mais do que só a memória

Esse bug não é exclusivo de perguntas de recuperação de memória — qualquer mensagem em português
que **nomeie algo** ("minha loja se chama X", "o produto se chama Y", "meu plano se chama Z")
caía no mesmo piso de segurança indevidamente, mostrando ao cliente um menu de confirmação de risco
físico ("Há um risco físico real acontecendo agora?") para uma frase completamente neutra. Isso é
pior do que só perder uma resposta — é confundir o cliente com uma pergunta de segurança sem
sentido numa conversa comum. Corrigido na raiz, não só para o caso de memória.
