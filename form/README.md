# Documentação Técnica: App `form` (Relatórios Técnicos de Veículos)

## 1. Visão Geral
O app `form` é a ferramenta de entrada de dados para diagnósticos veiculares. Ele gerencia o preenchimento de relatórios técnicos complexos que servem de base para o atendimento de suporte avançado.

## 2. Lógica de Formulários Dinâmicos
O aplicativo utiliza intensivamente **Django Forms** em conjunto com **AJAX** para prover uma experiência de usuário fluida em formulários técnicos extensos.
- **`forms.py`**: Define a estrutura dos campos (marca, modelo, sistema, erros encontrados).
- **Endpoint `get-opcoes/`**: Responsável pelo carregamento dinâmico de selects encadeados (ex: selecionar uma Marca carrega apenas os Modelos daquela marca).

## 3. Edição em Tempo Real (Dashboard de Edições)
Diferente de um CRUD tradicional, o app implementa uma interface de "edição em linha" no dashboard.
- **Endpoint `update-field/`**: Permite que um técnico altere um único campo de um relatório (ex: o campo "Sistema Eletrônico") via uma requisição assíncrona, sem recarregar a página.
- **Segurança**: Cada edição assíncrona é validada contra o esquema de formulário original para garantir a integridade dos dados.

## 4. Gerenciamento de Mídia Veicular
O formulário permite anexar fotos de sistemas eletrônicos e logs de erros.
- **Upload**: O sistema lida com o processamento de arquivos multipart integrados ao `form_save`.
- **Exibição**: As fotos são renderizadas no dashboard de forma otimizada para consulta rápida pelo técnico de suporte nível 2.

## 5. Especificações de API e Rotas
- `GET /form/get-opcoes/`: Recebe `marca_id` e retorna um JSON com a lista de modelos correspondentes.
- `POST /form/update-field/`: Recebe `record_id`, `field_name` e `value`; retorna confirmação de sucesso ou erros de validação.
- `GET /form/dashboard/`: Visão gerencial das últimas submissões e edições realizadas pela equipe.

## 6. Integração com o Fluxo de Suporte
Os relatórios gerados neste app são frequentemente anexados às ocorrências do app `ocorrencia_erro` para fornecer contexto técnico detalhado ao especialista que assumir o chamado.

## 7. Melhores Práticas de UI/UX
- O frontend utiliza bibliotecas de autocomplete e select dinâmico que dependem dos endpoints deste aplicativo.
- Mensagens de erro de validação são transmitidas via JSON e renderizadas dinamicamente no formulário.
