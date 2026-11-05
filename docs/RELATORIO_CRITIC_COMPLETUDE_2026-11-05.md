# Critic: completude de pergunta composta (05/11/2026, pós-publicação)

Mudança leve (só prompt, sem schema novo) em vez da decomposição completa com busca separada por
subpergunta — mais barata e de menor risco, visando a mesma causa (maior bucket de erro do Bloco 1:
33% "contexto certo, geração omitiu o fato").

## Mudança

`critic_agent.py::CRITIC_RULES["material"]`: o critério "not addressing the customer's request" já
existia; passou a dizer explicitamente que responder só uma parte de uma pergunta de várias partes,
tratando-a como respondida por completo, também é motivo de reprovação material.

## Medição (dev, 2 rodadas — ruído já conhecido desta sessão)

| | rodada 1 | rodada 2 | base (antes, hoje) |
|---|---|---|---|
| coverage_mean | 0,722 | 0,736 | 0,736 |
| full_coverage_rate | 0,694 | 0,722 | 0,722 |
| critic_rejection_rate | 0,025 | 0,050 | 0,050 |
| abstention_correct_rate | 0,667 | 1,000 | 1,000 |

A rodada 2 bate exatamente com a base — a queda da rodada 1 foi ruído (mesmo padrão já visto na
correção da pergunta composta). **Sem regressão**, mas também sem melhora clara detectável nesta
amostra de 40 itens — poucos casos de pergunta composta no dev para o efeito aparecer. Suite
completa (390/390) já verificada antes de medir.

## Decisão

**Adotada.** Risco baixo (só reforça um critério que já existe e já passa pelos mesmos testes do
Critic), mecanismo correto (ataca diretamente a causa nº1 do Bloco 1), sem regressão medida. Efeito
real só vai ficar visível numa amostra com mais perguntas compostas — não gastei mais uma rodada
cara pra confirmar isso, dado o pedido de eficiência.

## Não feito (fora do orçamento desta rodada)

Decomposição completa (separar em subperguntas com busca própria por parte) não foi implementada —
exigiria reestruturar `KnowledgeAgent.retrieve()`/`_generate()` para múltiplas chamadas e deduplicar
evidência, um escopo maior do que o pedido de eficiência comporta agora.
