# Documentação Técnica: App `pedido` (Checkout & Financeiro)

## 1. Visão Geral
O app `pedido` é o módulo financeiro responsável por transmutar orçamentos do simulador em vendas reais. Ele gerencia o checkout, a integração com o gateway de pagamento (Rede) e a posterior sincronização com o ERP Odoo.

## 2. Fluxo de Pagamento (Checkout)
A arquitetura do checkout segue um modelo de transição de estados baseado em tokens temporários (`uuid` no banco).

### 2.1. Cartão de Crédito/Débito (e-Rede)
1. **Início**: O usuário acessa `/pedido/pagamento/cartao/<token>/`.
2. **Autenticação 3D Secure (3DS)**: Se o cartão exigir autenticação forte (comum em débito), o sistema redireciona o cliente para o emissor do cartão via endpoint da Rede.
3. **Callbacks 3DS**: Após a autenticação no banco, o cliente retorna para `/pedido/3ds/c/<venda_id>/`, onde o sistema verifica o status do `ThreeDSecure`.
4. **Finalização**: Se bem-sucedido, o status da venda no banco de dados muda para `paid`.

### 2.2. PIX (QR Code Dinâmico)
1. **Geração**: O endpoint `/api/pagamento/pix/<token>/gerar/` solicita um QR Code dinâmico à Rede.
2. **Consultas**: O frontend realiza um "polling" no endpoint de consulta (`/api/pagamento/pix/<token>/consultar/`) para verificar se o pagamento foi confirmado.
3. **Webhook**: Em paralelo, o endpoint `/api/pagamento/pix/notificacao/` recebe um POST da Rede informando a liquidação do PIX de forma assíncrona.

## 3. Integração com ERP Odoo
Após a confirmação do pagamento (`status='paid'`), o sistema aciona um serviço de sincronização:
- **Criação de Cliente**: Se o cliente não existir no Odoo, ele é criado primeiro via XML-RPC.
- **Sale Order**: Um pedido de venda é gerado no Odoo com os itens da `VendaItem`.
- **Registro Financeiro**: O pagamento é conciliado no ERP para fins contábeis.

## 4. Regras de Negócio e Cálculos
- **Itens de Venda (`VendaItem`)**: Armazena o preço snapshot no momento da venda, protegendo a transação de futuras alterações de preço no catálogo global.
- **Arquivos (`VendaArquivo`)**: Permite que o vendedor anexe comprovantes de depósito bancário manual para vendas que não passam pelo gateway automático.

## 5. Especificações de API (Checkout)
- `POST /api/pagamento/cartao/<token>/pagar/`: Recebe dados do cartão (tokenizados) e processa a transação na Rede.
- `POST /api/pagamento/pix/notificacao/`: Processa payloads da Rede contendo `transaction_id` e `amount`.

## 6. Segurança e Auditoria
- Os dados sensíveis de cartão nunca tocam o banco de dados do sistema; o processamento é feito via SDK/API do gateway.
- Todas as requisições de pagamento são logadas para auditoria em caso de chargeback ou falha de comunicação.

## 7. Dependências
- `requests`: Para comunicação com a API REST da Rede.
- `xmlrpc.client`: Para sincronização com o Odoo.
