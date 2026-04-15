# Documentação Técnica: App `painel` (Dashboard & Segurança)

## 1. Visão Geral
O app `painel` é o hub central de operações do sistema. Ele provê a interface de usuário (UI), gerencia o Controle de Acesso Baseado em Funções (RBAC) e atua como o provedor de SSO e sincronização para sistemas satélites.

## 2. Controle de Acesso (RBAC & Setores)
Diferente do Django Admin, o `painel` implementa uma lógica de permissões departamentalizada.

### 2.1. Hierarquia de Usuários
- **Superuser**: Acesso total via Django Admin.
- **Gestor de Setor**: Pode criar, editar e resetar senhas de usuários vinculados ao seu setor (`usuarios.UsuarioProfile.setor`).
- **Colaborador**: Acesso limitado aos módulos permitidos pelo gestor.

### 2.2. Gestão de Sistemas (`PAINEL_SYSTEMS`)
O painel gerencia o acesso a múltiplos subsistemas (Ocorrência, Simulador, Pedidos, etc.) dinamicamente.
- O acesso é controlado pelo modelo `usuarios.UsuarioProfile` e validado via middleware/decoradores.
- O `context_processsors.painel_modules` injeta os links permitidos em todos os templates globalmente.

## 3. Integração SSO (BlockUnblock)
O sistema possui um endpoint de integração `/sso/blockunblock/`.
- **Propósito**: Sincronizar o status de bloqueio e as credenciais de usuários com o sistema central `BlockUnblock`.
- **Mecanismo**: Troca de chaves HMAC/Token para validar requisições entre os servidores de forma segura.

## 4. Gestão de Equipe (Autosserviço de Gestores)
Um recurso crítico do painel é permitir que gestores de setor (ex: Gerente de Suporte) operem como "admins limitados":
- Podem criar usuários em `/users/new/`.
- Podem resetar senhas de seus liderados sem intervenção do setor de TI.
- Podem definir quais sistemas o colaborador pode ver em `/users/<id>/systems/`.

## 5. Especificações de Rotas Principais
- `GET /dashboard/`: O coração do sistema. Renderiza cartões dinâmicos baseados no cargo e métricas de desempenho do usuário logado.
- `POST /users/<id>/password/`: Validação de segurança dupla antes do reset de senha via gestor.
- `POST /sso/blockunblock/`: Recebe instruções de bloqueio/desbloqueio de usuários do sistema externo.

## 6. Middlewares e Decoradores
- `middleware.py`: Garante que usuários inativos ou com o perfil incompleto sejam redirecionados.
- `decorators.py`: Contém `@setor_required(setores=[...])` e `@gestor_required` para proteção granular de views.

## 7. Temas e UI
- Utiliza **Vanilla CSS** e estruturas de grid customizadas para o layout do painel lateral e do grid de módulos.
- Ícones são servidos via SVGs estáticos ou fontes de ícones configuradas em `static/icons/`.
