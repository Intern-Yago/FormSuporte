# Documentação Técnica: App `simulador` (Frontend de Orçamentação)

## 1. Visão Geral
O app `simulador` é o portal de vendas da empresa. Ele provê a interface interativa (SPA ou similar) que permite aos vendedores montarem orçamentos complexos com base no estoque de equipamentos e regras comerciais.

## 2. Fluxo Comercial (Simulação)
O aplicativo funciona como um orquestrador de dados:
1. **Busca de Equipamentos**: Consome o aplicativo `API` (`/api/equipamentos/`) para obter o catálogo de hardware.
2. **Cálculo de Preços**: Solicita à API o cálculo tributário baseado no CPF/CNPJ e estado do cliente.
3. **Persistência Temporária**: Salva os dados no modelo `Registro` do app `API`, servindo de base para futuras conversões em pedidos.

## 3. Identificação e Rastreabilidade
- Cada simulação é vinculada ao vendedor logado via `request.user`.
- As simulações geram um `token` único que pode ser compartilhado com o cliente para visualização em PDF.

## 4. Integração com Geração de PDF
O simulador utiliza o endpoint `/api/generate-pdf/` para renderizar o orçamento oficial.
- O vendedor pode personalizar os termos de pagamento e validade do orçamento na interface do simulador antes de gerar o PDF.

## 5. Interface de Usuário (UI/UX)
- A interface é otimizada para uso em dispositivos móveis, permitindo que o vendedor faça simulações em campo.
- Utiliza componentes dinâmicos para gerenciar a "cesta" de equipamentos do orçamento.

## 6. Evolução para Venda
Uma simulação bem-sucedida é convertida em um pedido real através do app `pedido`.
- O ID do `Registro` da simulação é passado para o endpoint `/pedido/abrir/<id>/`, que inicia o fluxo de faturamento e checkout.

## 7. Melhores Práticas de Uso
- Recomenda-se que o vendedor sempre identifique o cliente (mesmo que apenas pelo nome) para facilitar a busca histórica de simulações.
- O simulador deve ser sincronizado frequentemente com a API para refletir mudanças de preços e disponibilidade de estoque.
