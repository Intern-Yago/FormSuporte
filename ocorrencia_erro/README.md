# Documentação Técnica e Funcional: App `ocorrencia_erro`

## 1. Visão Geral e Contexto (O "O quê" e o "Porquê")
O `ocorrencia_erro` é o sistema central de suporte pós-venda da EAATA. Ele foi projetado para resolver o problema de descentralização do atendimento técnico, permitindo que falhas em equipamentos sejam reportadas, diagnosticadas e resolvidas em uma interface única. 
- **Público-alvo**: Técnicos de Suporte (Nível 1 e 2) e Clientes finais/Vendedores.

## 2. Funcionalidades Principais (Visão de Usuário)
- **Abertura de Chamados**: Triagem técnica com captura de fotos e logs.
- **Chat Interativo**: Sala de conversa em tempo real dedicada a cada ticket.
- **Notificações em Push**: Alertas imediatos no dashboard sobre novas mensagens.
- **Geração de Laudo Técnico**: Exportação de PDF oficial com todo o histórico do chamado.
- **Filtros Inteligentes**: Busca por data, status, responsável e categoria.

## 3. Arquitetura e Fluxo de Dados (O "Como")
O aplicativo utiliza uma arquitetura **Event-Driven** para o chat e **Request-Response** para a gestão de tickets.
- **Fluxo de Mensagem**: 
  1. Frontend (JS) envia JSON via WebSocket -> 
  2. `ChatConsumer` valida permissão e decodifica anexos Base64 -> 
  3. Mensagem é salva no banco e transmitida para o grupo no Redis -> 
  4. Broadcast para todos os clientes conectados na sala.
- **Motor de PDF**: Utiliza `WeasyPrint` para converter o template HTML `dashboard_pdf.html` em arquivo binário.

## 4. Mapa de Navegação Técnica (O "Onde")
Para manutenções rápidas, consulte os seguintes blocos no arquivo `templates/ocorrencia/index.html`:
- **Lógica de Filtragem (JS)**: Linhas 2500-3050 (Funções `filterData`, `populateFilterBox`).
- **Árvore de Datas (JS)**: Linhas 2650-2750 (`createDateTreeHTML`).
- **Renderização da Tabela**: Linhas 3100-3350 (Looping de construção das linhas `<tr>`).
- **Integração com Chat (UI)**: Linhas 3750-4150 (Eventos de abrir/fechar chat e upload).

## 5. Regras de Negócio e Lógica Complexa (O "Cuidado")
- **Captura Automática de Solução**: O sistema monitora o chat através de uma Regex (`(?i)solu[cç][aã]o\s*[:\-]\s*(.+)`). Quando um técnico digita a palavra "Solução", o banco de dados é atualizado automaticamente.
- **RBAC Departamental**: A visibilidade de tickets é restrita ao `setor` do usuário logado. Gestores de Suporte (`cargo='gestor'`) têm visão global do seu departamento.
- **Sanitização de Dados**: Todas as mensagens registradas no histórico do Admin (`LogEntry`) passam pelo filtro de Regex para mascarar CPFs e CNPJs.

## 6. Integrações e Contratos (O "Com Quem")
### 6.1. Integrações Externas
- **DeepL API**: Endpoint `https://api-free.deepl.com/v2/translate`. Usado para tradução bidirecional (PT/ES).
- **MinIO/S3**: Bucket `eaata-seriais`. Armazena anexos de chat e fotos de ocorrências.
### 6.2. Integração Interna (Dependências)
- **`usuarios`**: Depende do `UsuarioProfile` para validar o setor e cargo.
- **`painel`**: Fornece os decoradores de acesso `@require_system_access`.
- **`form`**: Origem dos dados técnicos que iniciam a abertura de uma ocorrência.

## 7. Configuração e Dependências (O "Início")
- **Ambiente**: Necessário `REDIS_HOST` configurado para o funcionamento dos WebSockets.
- **Bibliotecas Python**: `channels`, `weasyprint`, `Pillow`, `python-magic`.
- **Daphne**: O servidor deve ser executado via ASGI para suportar o protocolo `ws://`.
