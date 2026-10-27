# Getnet Multi-Agent Support System

Sistema de atendimento inteligente desenvolvido para o desafio **AI Hardcore Engineer — Multi-Agent Support System**. A aplicação organiza o fluxo de atendimento por meio de agentes especializados, com uma API em FastAPI e uma interface web construída com React e TypeScript.

O projeto busca demonstrar uma arquitetura modular de atendimento, separando a identificação da intenção do usuário, a consulta à base de conhecimento, o suporte ao cliente e o encaminhamento de casos que exigem atendimento especializado.

## Sumário

- [Visão geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Arquitetura](#arquitetura)
- [Tecnologias utilizadas](#tecnologias-utilizadas)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Configuração e execução](#configuração-e-execução)
- [Endpoints da API](#endpoints-da-api)
- [Fluxo de atendimento](#fluxo-de-atendimento)
- [Base de conhecimento](#base-de-conhecimento)
- [Testes e validação](#testes-e-validação)
- [Qualidade de código e limitações conhecidas](#qualidade-de-código-e-limitações-conhecidas)
- [CI — Integração contínua](#ci--integração-contínua)
- [Demonstração](#demonstração)
- [Melhorias futuras](#melhorias-futuras)
- [Licença](#licença)

## Visão geral

O sistema recebe mensagens de usuários e direciona cada solicitação para o fluxo de atendimento mais adequado.

A solução foi estruturada em agentes especializados e componentes auxiliares, com o objetivo de facilitar a manutenção, a evolução e a avaliação de cada parte da aplicação.

O backend disponibiliza endpoints HTTP para interação com o sistema e consulta às fontes de conhecimento. A interface web permite que o usuário interaja com o atendimento por meio de uma aplicação visual.

## Funcionalidades

- **Roteamento de intenções:** identifica a categoria da solicitação e direciona o processamento para o agente apropriado.
- **Consulta à base de conhecimento:** recupera informações relevantes para apoiar as respostas.
- **Suporte ao cliente:** processa solicitações relacionadas ao atendimento.
- **Escalonamento:** identifica situações que podem exigir encaminhamento para atendimento humano ou especializado.
- **Guardrails:** aplica verificações de entrada e regras de segurança definidas pela aplicação.
- **Rastreabilidade:** inclui informações de fluxo e de agente na resposta, conforme o processamento realizado.
- **API REST:** disponibiliza endpoints para comunicação com o backend.
- **Interface web:** oferece uma interface de interação com o sistema.
- **Containerização:** utiliza Docker e Docker Compose para facilitar a execução e a validação do ambiente.

## Arquitetura

A aplicação é organizada em duas partes principais:

### Frontend

Interface web construída com React, TypeScript e Vite. O Nginx é utilizado na configuração de container do frontend para servir os arquivos da aplicação e encaminhar as chamadas de API conforme a configuração do projeto.

### Backend

API construída com FastAPI e Python. O backend contém os agentes, as regras de validação, os recursos de consulta à base de conhecimento e o serviço que coordena o atendimento.

### Agentes e componentes

| Componente | Responsabilidade |
|---|---|
| `RouterAgent` | Determina o fluxo de atendimento com base na intenção identificada. |
| `KnowledgeAgent` | Apoia as respostas utilizando a base de conhecimento disponível. |
| `SupportAgent` | Processa solicitações relacionadas ao suporte ao cliente. |
| `EscalationAgent` | Trata casos que exigem escalonamento. |
| `Guardrails` | Executa verificações e aplica regras de proteção definidas na aplicação. |
| `SupportTools` | Reúne ferramentas auxiliares utilizadas no fluxo de suporte. |
| `ChatService` | Coordena os componentes e consolida o resultado do atendimento. |

Os nomes acima refletem a organização dos componentes do projeto; o comportamento específico de cada agente depende de sua implementação.

## Tecnologias utilizadas

### Backend
- Python
- FastAPI
- Pydantic
- Uvicorn
- Requests
- Beautiful Soup

### Frontend
- React
- TypeScript
- Vite
- Nginx

### Infraestrutura e qualidade
- Docker
- Docker Compose
- Git e GitHub
- GitHub Actions
- Pytest, para a execução da suíte automatizada de testes

## Estrutura do projeto

```text
.
├── .github/
│   └── workflows/
│       └── build.yml
├── backend/
│   ├── app/
│   │   ├── agents/
│   │   │   ├── escalation_agent.py
│   │   │   ├── guardrails.py
│   │   │   ├── knowledge_agent.py
│   │   │   ├── router_agent.py
│   │   │   ├── support_agent.py
│   │   │   └── support_tools.py
│   │   ├── knowledge/
│   │   │   ├── corpus.json
│   │   │   └── ingest.py
│   │   ├── main.py
│   │   └── service.py
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── styles.css
│   ├── Dockerfile
│   ├── index.html
│   ├── nginx.conf
│   ├── package.json
│   └── vite.config.ts
├── .env.example
├── .gitignore
├── docker-compose.yml
├── LICENSE
└── README.md
```

A estrutura acima resume os arquivos principais da aplicação. Arquivos adicionais de configuração podem existir no projeto.

## Pré-requisitos

Para executar a aplicação em containers, são necessários:

- Docker Desktop instalado e em execução.
- Docker Compose disponível por meio do comando `docker compose`.
- Git, caso deseje clonar o repositório.

A execução por Docker reduz a necessidade de instalar manualmente as dependências Python e JavaScript na máquina local.

## Configuração e execução

### 1. Obter o código

Clone o repositório:

```bash
git clone https://github.com/SEU-USUARIO/getnet-multi-agent.git
cd getnet-multi-agent
```

Substitua `SEU-USUARIO` pelo nome de usuário ou organização responsável pelo repositório.

### 2. Configurar as variáveis de ambiente

Consulte o arquivo `.env.example` para identificar as variáveis de configuração disponíveis.

Se o projeto exigir um arquivo `.env`, crie-o localmente com os valores adequados. Não publique credenciais, tokens ou outras informações sensíveis no repositório.

### 3. Construir e iniciar os serviços

```bash
docker compose up --build -d
```

Esse comando solicita ao Docker Compose a construção das imagens e a inicialização dos serviços definidos no arquivo `docker-compose.yml`.

### 4. Verificar a inicialização

Consulte o estado dos containers:

```bash
docker compose ps
```

Consulte os logs, se necessário:

```bash
docker compose logs --tail=100
```

O endereço e a porta de acesso à interface dependem do mapeamento definido no `docker-compose.yml`. Verifique também se as portas necessárias estão disponíveis na máquina.

### 5. Encerrar os serviços

```bash
docker compose down
```

Esse comando encerra e remove os containers criados pelo Compose, sem remover automaticamente as imagens.

## Endpoints da API

### `GET /api/health`

Endpoint de verificação de saúde da aplicação.

Exemplo:

```bash
curl http://localhost:8000/api/health
```

O endpoint foi utilizado na validação do ambiente Docker e respondeu com **HTTP 200**.

### `GET /api/knowledge/sources`

Endpoint para consultar as fontes de conhecimento disponibilizadas pela aplicação.

Exemplo:

```bash
curl http://localhost:8000/api/knowledge/sources
```

O formato exato da resposta depende da implementação atual do endpoint.

### `POST /api/chat`

Endpoint para enviar uma mensagem ao sistema de atendimento.

Exemplo de requisição:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Preciso de ajuda com meu atendimento",
    "user_id": "user-001"
  }'
```

O payload inclui:

| Campo | Descrição |
|---|---|
| `message` | Mensagem enviada pelo usuário. O tamanho permitido é de 1 a 2.000 caracteres. |
| `user_id` | Identificador do usuário. Quando não informado, o sistema utiliza o valor padrão definido pela API. |

A resposta pode incluir informações como a mensagem de atendimento, a intenção identificada, o agente responsável, a confiança, as fontes consultadas, a necessidade de encaminhamento e os dados de rastreabilidade do fluxo, conforme a implementação.

## Fluxo de atendimento

O processamento de uma mensagem segue, em linhas gerais, as seguintes etapas:

1. **Recepção:** a API recebe e valida a requisição.
2. **Verificações iniciais:** os guardrails executam as validações previstas.
3. **Identificação e roteamento:** o componente de roteamento determina o caminho de atendimento.
4. **Processamento especializado:** o agente selecionado executa sua responsabilidade.
5. **Consulta de conhecimento:** quando aplicável, são utilizadas informações da base disponível.
6. **Escalonamento:** casos que atendem às regras definidas podem ser encaminhados para tratamento especializado.
7. **Resposta:** o serviço consolida os resultados e devolve a resposta pela API.

O fluxo exato depende das regras e condições implementadas nos componentes do backend.

## Base de conhecimento

O projeto mantém uma base de conhecimento em `backend/app/knowledge/corpus.json` e utiliza o módulo `ingest.py` para carregar os documentos.

Durante a inicialização do backend no ambiente Docker validado, os logs indicaram o carregamento de **28 unidades de conhecimento**.

Esse resultado confirma o carregamento registrado no ambiente testado. Ele não representa, isoladamente, uma avaliação da precisão ou da cobertura das respostas produzidas pelo sistema.

## Testes e validação

A validação foi realizada com foco na execução da aplicação em containers, na suíte automatizada disponível e na verificação básica da API.

### 1. Execução da suíte automatizada

O comando utilizado para executar os testes no ambiente Docker foi:

```bash
docker compose --profile test run --build --rm tests
```

O comando solicita ao Docker Compose que construa a imagem necessária, quando aplicável, execute o serviço `tests` definido no perfil `test` e remova o container de teste ao final.

**Resultado registrado: 25 testes automatizados aprovados.**

A suíte foi executada no ambiente Docker, evitando depender diretamente da versão de Python instalada na máquina do desenvolvedor.

O resultado confirma a aprovação dos testes executados nessa rodada. Para uma avaliação completa, é importante verificar no código da suíte quais cenários estão cobertos, incluindo validações de entrada, roteamento, respostas dos agentes, guardrails, escalonamento e tratamento de erros.

### 2. Verificação de saúde da API

Foi realizada uma chamada ao endpoint:

```http
GET /api/health
```

Resultado observado:

- Status HTTP: `200 OK`
- API acessível no ambiente local: `http://localhost:8000`

O resultado confirma que o endpoint de saúde respondeu com sucesso naquele ambiente e momento. Não comprova, por si só, que todas as funcionalidades da API estejam operacionais.

### 3. Carregamento da base de conhecimento

Durante a inicialização do backend, os logs indicaram:

```text
knowledge_loaded=28
```

Esse resultado indica que 28 unidades de conhecimento foram carregadas pelo processo de inicialização observado.

A quantidade carregada não deve ser confundida com uma métrica de precisão, relevância ou qualidade das respostas.

### 4. Construção dos containers

As imagens Docker foram construídas durante o processo de validação.

A construção das imagens permite verificar parte da configuração de empacotamento e das dependências necessárias para executar a aplicação. A construção bem-sucedida, isoladamente, não garante que todos os fluxos de negócio funcionem corretamente.

### 5. Validação da interface web

A validação integrada da interface web permaneceu pendente durante a rodada registrada, pois a inicialização do serviço web encontrou conflito na porta `8080`: a porta já estava alocada por outro processo.

Esse problema de ambiente não deve ser apresentado como uma falha funcional confirmada da interface, mas também não permite afirmar que a interface foi validada integralmente no navegador.

Para concluir essa verificação, é necessário liberar a porta ocupada ou ajustar o mapeamento de portas no Docker Compose e, em seguida, abrir a interface no navegador e testar o fluxo completo de atendimento.

### 6. Resumo dos resultados

| Verificação | Resultado registrado | Interpretação |
|---|---|---|
| Suíte automatizada no Docker | 25 testes aprovados | Os testes executados passaram. |
| `GET /api/health` | HTTP 200 | O endpoint de saúde respondeu com sucesso. |
| Carregamento do conhecimento | 28 unidades | O carregamento foi registrado nos logs. |
| Construção das imagens Docker | Executada | As imagens foram construídas no ambiente de validação. |
| Interface no navegador | Pendente | A validação foi impedida pelo conflito na porta 8080. |
| Fluxo integrado completo pela interface | Pendente de confirmação | É necessário concluir a validação no navegador. |

### 7. Estratégia de testes recomendada

Para fortalecer a cobertura e a confiabilidade do sistema, recomenda-se manter ou ampliar testes automatizados para os seguintes cenários:

- **API:** códigos HTTP, validação de payloads, campos obrigatórios e mensagens inválidas.
- **Roteamento:** seleção do agente esperado para diferentes tipos de solicitação.
- **Base de conhecimento:** carregamento dos documentos, fontes disponíveis e ausência de resultados relevantes.
- **Guardrails:** entradas vazias, mensagens fora dos limites permitidos e tentativas de contornar as regras do sistema.
- **Suporte:** respostas para solicitações previstas e tratamento de situações não reconhecidas.
- **Escalonamento:** identificação dos casos que devem ser encaminhados e sinalização correta dessa necessidade.
- **Erros e dependências:** falhas de processamento, exceções e indisponibilidade de recursos.
- **Frontend:** envio de mensagens, exibição de respostas, estados de carregamento e apresentação de erros.
- **Integração:** comunicação real entre frontend, API e base de conhecimento.
- **Regressão:** execução da suíte a cada alteração relevante do código.

Esses itens representam uma estratégia recomendada. Não devem ser interpretados como testes individualmente aprovados sem evidências da execução correspondente.

## Qualidade de código e limitações conhecidas

O projeto está organizado em módulos que separam a API, os agentes, as ferramentas auxiliares, a base de conhecimento e a interface web. Essa separação facilita a manutenção e permite evoluir componentes de forma mais independente.

A avaliação de qualidade deve considerar, além da organização dos arquivos:

- clareza e consistência das responsabilidades;
- tratamento de erros e validação de entradas;
- testes unitários e de integração;
- segurança na configuração e no tratamento de dados;
- logs úteis para diagnóstico;
- documentação atualizada;
- facilidade de instalação e reprodução do ambiente.

### Limitações conhecidas da validação

- A validação automatizada registrada corresponde a 25 testes aprovados na execução via Docker.
- A cobertura exata de cada requisito deve ser confirmada pela leitura dos casos de teste.
- A validação completa da interface no navegador não foi concluída na rodada registrada.
- O conflito na porta `8080` precisa ser resolvido para repetir o teste integrado da interface.
- O carregamento de documentos não constitui, sozinho, uma avaliação de qualidade das respostas.
- A operação de integrações externas, quando existentes, deve ser validada separadamente e não é presumida apenas pela aprovação dos testes.

## CI — Integração contínua

O projeto inclui um workflow em `.github/workflows/build.yml`, configurado para ser executado em eventos de `push` e `pull_request` direcionados à branch `main`.

O workflow define verificações para o backend e o frontend:

- instalação das dependências do backend e compilação dos módulos Python;
- instalação das dependências do frontend e execução do build de produção.

Essas etapas verificam aspectos importantes da integridade do código, mas **não substituem automaticamente a suíte de 25 testes executada no Docker**, a menos que o workflow também execute os testes.

A execução bem-sucedida do workflow no GitHub deve ser confirmada na aba **Actions** do repositório após o envio do código.

## Demonstração

Vídeo de demonstração: **[ADICIONE AQUI O LINK DO VÍDEO]**

A demonstração deve apresentar, preferencialmente:

1. Inicialização da aplicação.
2. Interface web aberta no navegador.
3. Envio de uma mensagem pelo usuário.
4. Resposta gerada pelo sistema.
5. Exemplos de diferentes intenções ou agentes, quando disponíveis.
6. Consulta à base de conhecimento e encaminhamento, quando aplicáveis.
7. Verificação dos endpoints da API.
8. Execução dos testes automatizados e apresentação do resultado.

## Melhorias futuras

- Ampliar a cobertura dos testes unitários, de integração e de interface.
- Executar a suíte automatizada também no pipeline de CI.
- Concluir e documentar a validação integrada no navegador.
- Aprimorar a avaliação da precisão do roteamento e da relevância das respostas.
- Adicionar métricas de qualidade, latência e taxa de escalonamento.
- Melhorar a observabilidade e o tratamento de falhas.
- Documentar exemplos reais de requisições e respostas da API.
- Revisar continuamente os guardrails e a segurança do fluxo de atendimento.

## Licença

Consulte o arquivo [`LICENSE`](LICENSE) para obter as condições de uso e distribuição deste projeto.
