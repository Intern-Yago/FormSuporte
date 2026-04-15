# 📊 EAATA - Módulo de KPIs e Equipamentos

Este é o módulo oficial de indicadores de desempenho (KPIs) e controle de equipamentos do sistema EAATA.

## 🚀 Principais Funcionalidades

### 1. Dashboard de Suporte (KPIs)
* **Métricas em Tempo Real:** Cálculo de totais de atendimentos, médias diárias, separação por categorias (Chaveiro vs. Diagnóstico) e identificação automática do "Campeão" do período.
* **Filtros Avançados de Período:** Motor de busca que permite filtrar desde um único mês, até um período customizado (ex: *DE Fev/2025 ATÉ Set/2026*), calculando dias úteis exatos dinamicamente via backend.
* **Histórico Geral (All-Time):** Gráfico de linha do tempo que se expande para mostrar toda a evolução do setor de suporte desde a fundação da empresa.
* **Visão Individual (One-on-One):** Filtro por técnico específico, permitindo que a diretoria e os gestores avaliem a curva de desempenho e as notas de um colaborador isoladamente.

### 2. Painel de Equipamentos
* **Controle de Ciclo de Vida:** Identificação automática de máquinas "Ativas", "A Vencer", "Vencidas" e "Bloqueadas" com base nas datas selecionadas.
* **Filtro Inteligente de Múltipla Escolha:** Menu dropdown customizado (checkboxes) que permite cruzar a busca de vários modelos de máquinas simultaneamente.
* **Padronização Automática:** Limpeza de dados no backend que agrupa nomenclaturas diferentes digitadas no banco (ex: *EAATA360 PRO* e *EAATA 360 PRO*) em uma única categoria visual.

### 3. Exportação Nativa
* **Exportar XLSX (Excel):** Geração instantânea de planilhas usando a biblioteca **SheetJS** no lado do cliente, espelhando exatamente os dados e colunas visíveis na tabela após a aplicação dos filtros.
* **Exportar PDF:** Geração de relatórios gerenciais idênticos à tela do sistema, utilizando **html2pdf.js**, com ajuste automático de `pagebreak` e redimensionamento para uma única folha em alta resolução.

### 4. Segurança e Controle de Acesso (RBAC)
* Integração total com o modelo `UsuarioProfile`.
* Colaboradores comuns não têm acesso aos painéis estratégicos (são redirecionados automaticamente).
* Acesso restrito por hierarquia: `Dono`, `Diretor` e `TI` possuem visão global de todos os setores. `Gestores` possuem acesso limitado ao seu próprio setor (ex: Gestor Comercial não vê KPIs do Suporte).

---

## 🛠️ Tecnologias Utilizadas

* **Backend:** Python 3, Django (Views, Models, ORM Avançado com `annotate` e `Sum`).
* **Frontend:** HTML5, CSS3 (Variáveis CSS, CSS Grid/Flexbox), JavaScript Vanilla (ES6+).
* **Bibliotecas JS:** * `Chart.js` (Renderização de gráficos interativos).
    * `SheetJS` (`xlsx.full.min.js` para exportação de planilhas).
    * `html2pdf.js` (Captura de tela e conversão em PDF canvas).

---

## 📂 Arquitetura e Roteamento (URLs Modularizadas)

O sistema foi desenhado para ser escalável. As rotas não estão misturadas em um único arquivo. O tráfego é roteado do app principal para o setor específico:

```text
kpis/
├── urls.py                 # Roteador Principal (Delega rotas por setor)
├── views.py                # Redirecionamentos e lógicas globais
├── services.py             # Regras de negócio e cálculos de banco de dados
├── setores/
│   ├── suporte/
│   │   ├── urls.py         # Rotas específicas do Suporte
│   │   ├── views_suporte.py# Controladores (Dashboard, APIs)
│   ├── comercial/          # (Estrutura pronta para expansão futura)
│   └── marketing/          # (Estrutura pronta para expansão futura)