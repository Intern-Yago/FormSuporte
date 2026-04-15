# Documentação Técnica: App `API` (Serviços REST & PDF)

## 1. Visão Geral
O app `API` fornece a infraestrutura de backend para o simulador comercial e outros serviços externos. Ele utiliza o **Django Rest Framework (DRF)** para oferecer uma interface de dados limpa e escalável.

## 2. Arquitetura de Dados (Equipamentos)
O sistema gerencia um catálogo complexo de hardware com as seguintes entidades:
- **`MarcaEquipamento`**: Fabricantes (ex: EAATA, Sun, etc.).
- **`TipoEquipamento`**: Categorias (ex: Scanners, Programadores, etc.).
- **`Equipamentos`**: O modelo central que contém as especificações técnicas, preços e metadados.

### 2.1. Lógica de Precificação Dinâmica
A API não retorna apenas um valor fixo. Ela implementa lógica tributária e comercial:
- **Diferenciação Tributária**: Cálculos distintos para Pessoa Física (CPF) e Pessoa Jurídica (CNPJ).
- **Substituição Tributária (ST)**: Ajuste de preços para vendas originadas em SP para outros estados.

## 3. Geração de Documentos PDF
A geração de PDFs é um dos recursos mais críticos e complexos da API.
- **Ferramenta**: `WeasyPrint`.
- **Motor de Renderização**: Converte templates HTML/CSS dinâmicos em arquivos PDF de alta qualidade.
- **Workflow**:
  1. O cliente (Simulador ou Vendedor) envia os dados do orçamento via POST.
  2. A API processa o template `pdf_template.html` com os dados recebidos.
  3. O `WeasyPrint` renderiza o PDF em memória e retorna o stream de bytes para download instantâneo.

## 4. Endpoints e Autenticação
- **Autenticação**: Suporte a `TokenAuthentication` via `/api/api-token-auth/`.
- **ViewSets**:
  - `GET /api/equipamentos/`: Listagem com filtros de marca e tipo.
  - `POST /api/generate-pdf/`: Endpoint de alta performance para geração sob demanda.
- **Busca de Clientes**: O endpoint `/api/clientes/search/` permite encontrar clientes vinculados a equipamentos específicos no suporte via número de série.

## 5. Simulador Comercial (Registros)
O modelo `Registro` armazena o histórico de simulações realizadas.
- O endpoint `/api/registros/<id>/atualizar/` permite que simulações salvas sejam modificadas antes de se tornarem pedidos definitivos no app `pedido`.

## 6. Requisitos de Sistema (Backend)
Para o funcionamento correto do `WeasyPrint`, o ambiente deve ter as seguintes bibliotecas C instaladas:
- `pango`, `cairo`, `gdk-pixbuf`.

## 7. Melhores Práticas de Integração
- **Filtros**: Sempre utilize os parâmetros de query para limitar a carga de dados nos ViewSets de equipamentos.
- **Cache**: Recomenda-se o uso de cache nos endpoints de listagem de equipamentos, dado que o catálogo de hardware muda com pouca frequência.
