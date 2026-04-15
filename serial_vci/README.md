# Documentação Técnica: App `serial_vci` (Gestão de Hardware VCI)

## 1. Visão Geral
Este aplicativo é dedicado ao ciclo de vida físico dos equipamentos VCI. Ele gerencia desde o cadastro inicial do número de série até o histórico de fotos de inspeção e processos de garantia técnica.

## 2. Inventário Fotográfico (`SerialFoto`)
O app implementa um sistema de documentação visual para evitar fraudes e facilitar o suporte remoto.
- **Armazenamento**: As fotos são enviadas para o bucket `eaata-seriais` (MinIO/S3).
- **Processamento**: O sistema gera URLs assinadas temporárias para exibição das fotos no frontend, garantindo que as imagens não fiquem expostas publicamente.
- **Mecanismo de Limpeza**: A remoção de fotos no banco (`remover_foto`) aciona automaticamente a exclusão do objeto no MinIO.

## 3. Fluxo de Garantia Técnica
O modelo `Garantia` centraliza os pedidos de reparo ou troca de equipamentos.
- **Registro de Comentários**: Possui um sistema de thread de comentários (`GarantiaComentario`) que permite o diálogo técnico entre o laboratório e o vendedor/técnico de campo.
- **Notificações em Tempo Real**: O app utiliza **Django Channels** (`SerialConsumer`) para notificar os técnicos de laboratório sempre que um novo processo de garantia é aberto.

## 4. Integração de Dados
- **Relacionamento**: Um `Serial` pode estar vinculado a um `Cliente` (do app `clientes`) para rastreabilidade de propriedade.
- **Validação**: O campo de número de série possui validações de regex para garantir que apenas seriais válidos da EAATA sejam cadastrados.

## 5. Especificações de Rotas Principais
- `GET /seriais/detalhes/<id>/`: Ficha técnica completa do equipamento, incluindo galeria de fotos e histórico de garantias.
- `POST /seriais/<id>/garantia/add/`: Inicia o processo de garantia solicitando o motivo técnico inicial.
- `POST /seriais/remover_foto/<id>/`: Endpoint seguro que valida a propriedade da foto antes da exclusão física.

## 6. WebSockets (Real-time Status)
- **Canal**: `serial_updates`.
- **Evento**: `new_warranty_request`.
- **Payload**: ID do serial, motivo e solicitante. Isso permite que o laboratório tenha um dashboard "vivo" das entradas de equipamentos.

## 7. Dependências
- `channels`: Protocolo WebSocket.
- `boto3`: Comunicação com o sistema de arquivos MinIO.
