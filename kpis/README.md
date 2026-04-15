# Documentação Técnica: App `kpis` (Indicadores de Desempenho)

## 1. Visão Geral
O app `kpis` é o módulo de inteligência de dados do sistema. Ele é responsável por extrair métricas de performance dos outros aplicativos (especialmente do suporte) e fornecer indicadores agregados para tomada de decisão gerencial.

## 2. Estrutura por Setores (Modularidade)
O aplicativo adota uma estrutura modular interna em `kpis/setores/`. Cada setor possui sua própria lógica de negócio isolada:
- **`suporte/`**: O módulo mais maduro. Calcula produtividade de técnicos, volume de chamados e tempos de resposta.
- **`comercial/`, `financeiro/`, `marketing/`, `ti/`**: Estruturas preparadas para futura expansão de métricas específicas.

## 3. Lógica de Cálculo de Métricas (Suporte)
A lógica principal reside em `kpis/setores/suporte/services.py`.
- **Tempo Médio de Atendimento (TMA)**: Calculado com base na diferença entre `created_at` e `finished_at` do modelo `Record` de ocorrências.
- **Taxa de Resolução**: Proporção de tickets finalizados em relação ao total aberto no período.
- **Métricas por Técnico**: Agregação de dados por usuário para identificar gargalos ou alta performance.

## 4. Arquitetura de Fornecimento de Dados (JSON API)
Os dados não são renderizados diretamente via Django Templates para os gráficos.
- O aplicativo fornece uma série de endpoints JSON que são consumidos por bibliotecas de gráficos no frontend (como Chart.js ou ApexCharts).
- **Séries Temporais**: Endpoints como `/api/kpi/time-series/` fornecem dados agrupados por dia/mês para visualização de tendências.

## 5. Especificações de API (Suporte)
- `GET /kpis/suporte/api/technicians/`: Retorna a lista de técnicos e seus status de atividade.
- `GET /kpis/suporte/api/kpi/summary/`: Resumo executivo dos KPIs do mês corrente.
- `GET /kpis/suporte/api/equipamentos/summary/`: Estatísticas sobre quais equipamentos geram mais chamados de suporte.

## 6. Persistência de Dados Históricos
O sistema utiliza o modelo `usuarios.KpiRegistroMensal` para congelar as métricas de cada mês.
- Isso permite que o sistema mantenha um histórico de performance de longo prazo, mesmo que os registros de ocorrências originais sejam arquivados ou modificados.

## 7. Performance e Otimização
Devido ao grande volume de dados de ocorrências, o aplicativo utiliza:
- **Agregações ORM**: `Count`, `Avg`, `Sum` do Django para processamento eficiente no banco de dados.
- **Filtros de Data**: Todas as queries são otimizadas por range de data (`created_at__range`).
- **Cache (Recomendado)**: Devido à natureza estatística, as métricas do dia podem ser cacheadas para reduzir a carga no banco.
