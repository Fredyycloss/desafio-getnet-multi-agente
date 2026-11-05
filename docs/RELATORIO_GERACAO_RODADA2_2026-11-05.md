# Geração — rodada 2 (05/11/2026, pós-publicação)

Continuação do Bloco 3 depois de fechar a missão V8: item 3.5 (`claude-haiku-5-5` ×
`claude-sonnet-5-5` só na redação do Knowledge), que tinha ficado como "não testado por tempo".

## Metodologia

Para isolar só a etapa de redação (não a busca, não o reranking, não a escolha de ferramenta):
busquei a evidência **uma única vez** por pergunta (com o agente de produção, haiku) e chamei
`KnowledgeAgent._generate()` diretamente duas vezes sobre a **mesma evidência** — uma instância
com `claude-haiku-5-5`, outra com `claude-sonnet-5-5` — e comparei com as mesmas checagens
determinísticas usadas no resto da missão (`deterministic_checks`). Amostra: 25 dos 66 itens do
`quality_test_v2` (parei em 25 porque o sinal já estava decidido — zero variação entre os
modelos — ver abaixo).

## Resultado

| Modelo | cobertura média | cobertura total (100%) | números suportados | citação correta | custo médio | latência média |
|---|---|---|---|---|---|---|
| haiku | 0,947 | 0,880 | 1,000 | 1,000 | US$0,00026 | 1,31s |
| sonnet | 0,947 | 0,880 | 1,000 | 1,000 | US$0,00028 | 2,34s |

**Idêntico item a item** nas três checagens determinísticas (cobertura, números, citação) — não só
na média, em cada uma das 25 perguntas. O sonnet não errou nem acertou nada que o haiku já não
fizesse igual. A única diferença real: sonnet **79% mais lento** (2,34s vs 1,31s) pelo mesmo custo.

## Achado colateral: bug de compatibilidade

Ao configurar `claude-sonnet-5-5` pela primeira vez neste script, a chamada falhou com
`BadRequestError 400`: "To turn thinking off on this model, send `thinking: {type: between_tools}`
instead of `{type: disabled}`". O `AnthropicProvider` manda `{"type": "disabled"}` por padrão
(`ANTHROPIC_THINKING=disabled`) — funciona com `claude-haiku-5-5` mas **quebra** com
`claude-sonnet-5-5`, que não aceita esse valor. `run_answer_quality.py::judge_provider()` já
contornava isso manualmente (`judge_llm.thinking = "omit"`) para o juiz, mas o fix nunca foi geral
— se alguém algum dia apontar `ANTHROPIC_MODEL=claude-sonnet-5-5` como provedor principal sem saber
desse detalhe, toda chamada sem esse ajuste manual quebra. Não alterei o provedor nesta rodada
(escopo do item era só comparar os modelos, não corrigir o provedor) — fica documentado como risco
de portabilidade para quem for trocar o modelo principal no futuro.

## Decisão

**Manter `claude-haiku-5-5`** na redação do Knowledge. Sem ganho de qualidade mensurável nas
checagens determinísticas, custo igual, latência pior. Não justifiquei gastar numa comparação pelo
juiz LLM (mais cara) dado que a amostra determinística já não mostrou nenhuma diferença para o
juiz potencialmente captar — mas registro a ressalva: as checagens determinísticas não veem
nuance/fluência, só fundamentação factual; se um dia a nota do juiz (`corretas`) ficar estagnada
bem abaixo da meta, vale medir a mesma comparação com o juiz antes de descartar sonnet de vez.
