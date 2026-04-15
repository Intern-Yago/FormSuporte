# Documentação Técnica: App `clientes` (Base Central de Parceiros)

## 1. Visão Geral
Este aplicativo é o hub de dados cadastrais de todos os clientes do sistema. Ele gerencia a conformidade de dados (CPF/CNPJ) e garante a consistência com o ERP Odoo.

## 2. Modelagem de Clientes e Endereços
- **`Cliente`**: O modelo unificado. Possui validações específicas para Pessoa Física e Pessoa Jurídica. O campo `odoo_id` é preenchido após a sincronização inicial.
- **`ClienteEndereco`**: Suporta múltiplos endereços de entrega e faturamento por cliente, com suporte a geocodificação simplificada via campos de estado e cidade.

## 3. Sincronização XML-RPC com Odoo
O app é o proprietário dos drivers de comunicação com o Odoo:
- **`integrations/odoo_client.py`**: Encapsula as chamadas XML-RPC, lidando com autenticação e tratamento de exceções do ERP.
- **`services/odoo_sync.py`**: Contém a lógica de negócio para evitar duplicidade de cadastros no ERP, realizando buscas prévias por documento (CPF/CNPJ) antes de criar novos registros.

## 4. Interface de Gestão (Painel de Clientes)
O app provê uma interface de busca rápida e detalhamento de clientes no painel.
- **Endpoint `/clientes/`**: Utiliza filtragem otimizada por nome, documento ou e-mail.
- **Endpoint `/clientes/<id>/`**: Ficha técnica do cliente, exibindo todos os equipamentos (seriais) vinculados e histórico de pedidos.

## 5. Regras de Conformidade
- O sistema não permite o cadastro de clientes sem um documento válido (CPF ou CNPJ).
- Endereços são validados para garantir que possuam os campos mínimos necessários para o faturamento no Odoo (CEP, Rua, Número, Bairro, Cidade, Estado).

## 6. Dependências
- `xmlrpc.client`: Padrão do Python para comunicação com o Odoo.
- `django-br-utils`: Para formatação e validação de documentos fiscais brasileiros.
