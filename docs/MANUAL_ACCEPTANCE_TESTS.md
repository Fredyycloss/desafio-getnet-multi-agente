# Roteiro manual de aceite — interpretação, esclarecimento e handoff

Use a interface em `http://localhost:8080` com o stack em execução. A conta e os registros são sintéticos. A fila humana é local e simulada; nenhum atendente Getnet real recebe as solicitações.

## Preparação

1. Inicie o stack. No modo nuvem, use `docker compose up -d --build` com `GETNET_ANTHROPIC_API_KEY` no `.env`. No modo offline, use `bash scripts/start-ai.sh -d`.
2. Confirme em `http://localhost:8000/api/health` que `llm_available` é verdadeiro e veja o provedor ativo em `llm_provider`.
3. Abra o site e entre com uma conta demo (`cliente1988` / PIN `1988`). Inicie uma conversa nova e confirme o status “Sistema operacional”.

## Fluxo principal

### Pergunta clara

1. Envie: **“A Get Lite tem aluguel mensal?”**
2. Abra os detalhes da resposta.
3. Confirme `context_intelligence` no início do fluxo e depois Knowledge/Supervisor, fontes da resposta e Critic após a resposta automatizada.

### Esclarecimento contextual e seleção por botão

1. Inicie uma conversa nova e envie: **“Minha máquina está estranha e não sei o que está acontecendo.”**
2. Confirme que aparecem opções relacionadas a conexão, realização de vendas, funcionamento da maquininha e pagamentos, além de atendimento humano.
3. Clique em **“Problemas de conexão”**.
4. Confirme que o texto original continua no histórico, Context Intelligence é executado novamente e a opção escolhida chega ao Customer Support Agent, que faz uma pergunta objetiva para completar os dados. Uma pergunta nova fora do menu deve voltar ao fluxo normal do Supervisor.

### Seleção por número e por texto

1. Em uma conversa nova, peça esclarecimento com **“Não sei o que aconteceu com a minha maquininha.”**
2. Responda com o número `1`; confirme a seleção da primeira opção do menu vigente.
3. Repita e responda com o rótulo da opção, por exemplo **“Problemas para realizar vendas”**.
4. Confirme que ambos os formatos reavaliam o contexto e não repetem o mesmo menu sem necessidade.

### Mudança de assunto durante o esclarecimento

1. Quando o menu aparecer, envie uma solicitação completa de outro assunto, por exemplo: **“Na verdade, quero saber se a Get Lite tem aluguel mensal.”**
2. Confirme que a nova mensagem não é tratada como seleção do menu antigo e segue para Knowledge Agent.

## Atendimento humano

1. Antes de enviar qualquer texto, clique no botão visível **“Falar com atendente”**.
2. Confirme a resposta de registro, um protocolo e o status `queued`/aguardando atendimento.
3. Confirme que a interface informa que nenhum atendente real está conectado.
4. Clique em **“Status do atendimento”** e confirme que o estado é consultado novamente pela API.
5. Envie uma atualização na conversa. Confirme que ela aparece no protocolo e no histórico da sessão.
6. Em outra conversa, envie **“Não quero falar com robô, transfira para alguém.”** Confirme que a solicitação humana é registrada sem chamar agentes de domínio ou Critic.
7. Opcional, para demonstrar operação: configure localmente `OPERATOR_API_KEY`, consulte `/api/operator/queue`, assuma o ticket e faça uma resposta/resolução com as rotas de operador documentadas no README.

## Linguagem figurativa e segurança

1. Envie **“Essa máquina é uma bomba.”** Confirme que o sistema pede contexto e oferece opções, incluindo atendimento humano; não deve afirmar sem evidência que há explosivo nem iniciar troubleshooting.
2. Envie **“A bateria do terminal está estufada.”** Confirme orientações imediatas para afastar-se/não usar o equipamento e a criação de ticket crítico; a política determinística tem prioridade.
3. Envie **“Não quero falar com robô, quero um atendente.”** Confirme prioridade do pedido humano e a confirmação explícita de fila simulada.

## Verificação técnica opcional

Para consultar o registro criado, use o protocolo mostrado na interface: `GET /api/handoffs/{protocolo}?user_id=cliente1988`. O JSON precisa indicar `status`, `session_id`, mensagens anteriores e `real_agent_connected: false`. A consulta global à fila requer `X-Operator-Key` e `X-Operator-ID`.

## Registro de aceite

Anote data, navegador, estado de `/api/health`, protocolo de handoff, fluxo/trace das perguntas claras e ambíguas, e qualquer divergência observada. Não inclua dados pessoais, senhas, tokens ou números de cartão no teste.
