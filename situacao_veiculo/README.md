# Documentação Técnica: App `situacao_veiculo` (Regras de Negócio de Suporte)

## 1. Visão Geral
Este aplicativo é o guardião das regras de elegibilidade para suporte técnico. Ele determina se um equipamento (serial) tem direito a atendimento com base em garantias, contratos e status financeiro.

## 2. Lógica de Determinação de Status
O motor de decisão do aplicativo avalia o número de série e retorna um dos seguintes estados:
- **`Liberado`**: Equipamento com suporte ativo e validado.
- **`Vencido`**: Garantia ou contrato de suporte expirado; o sistema sugere a renovação.
- **`Bloqueado`**: Suspensão manual (ex: inadimplência) ou erro crítico de registro.
- **`Sem Registro`**: Serial não encontrado na base local ou no Odoo.

## 3. Integração Multicamada (Odoo & BlockUnblock)
O status final é o resultado de uma consulta a múltiplas fontes:
1. **Base Local**: Cache de seriais e status manuais.
2. **Odoo (ERP)**: Consulta via XML-RPC para verificar datas de garantia e validade de contratos de serviço.
3. **BlockUnblock (Webhook)**: Recebe notificações assíncronas de sistemas externos que bloqueiam ou liberam o suporte em tempo real.

## 4. Auditoria de Consultas (`SerialSearchLog`)
Dado que o acesso a dados de clientes é sensível, o app implementa um sistema de auditoria rigoroso:
- Cada busca por serial é registrada no modelo `SerialSearchLog`.
- Registra-se o usuário que realizou a busca, o serial consultado, a data e o status retornado.
- O arquivo `audit.py` encapsula essa lógica para garantir que nenhuma consulta passe sem registro.

## 5. Funcionalidades de Gestão
- **Importação em Lote**: Suporte a upload de arquivos Excel (`.xlsx`) para atualização massiva de seriais e clientes.
- **Monitoramento de Contato**: Interface para que a equipe de suporte marque que um cliente foi "contactado", prevenindo duplicidade de abordagem comercial para renovação de suporte.

## 6. Especificações de API e Webhooks
- `POST /webhooks/situacao/equipment-status/`: Recebe payloads JSON externos para mudar o status de um equipamento instantaneamente.
- `GET /situacao/api/cliente/`: Fornece dados sanitizados do proprietário do equipamento para o frontend.

## 7. Dependências
- `pandas` / `openpyxl`: Processamento de arquivos Excel.
- `xmlrpc.client`: Comunicação com o ERP Odoo.
- `django-br-utils` (opcional): Validação de CPF/CNPJ.
