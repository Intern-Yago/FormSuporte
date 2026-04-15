# Documentação Técnica: App `usuarios` (Infraestrutura de Perfil)

## 1. Visão Geral
Este aplicativo estende o sistema de autenticação padrão do Django para suportar a complexidade organizacional da empresa (setores, cargos e países).

## 2. Modelo `UsuarioProfile` (Core)
O `UsuarioProfile` é o modelo central de metadados do usuário.
- **`setor`**: Define a qual departamento o usuário pertence (Suporte, Comercial, etc.). Crucial para o RBAC do painel.
- **`cargo`**: Utilizado para determinar permissões de gestão (ex: um gestor pode resetar senhas).
- **`pais`**: Controla o idioma padrão e as regras de localidade aplicadas ao usuário.
- **`odoo_user_id`**: O link vital para a sincronização de logs e atividades com o ERP Odoo.

## 3. Mecanismo de Sincronização (Signals)
O app utiliza **Django Signals** para garantir a integridade referencial:
- **`post_save`**: Assim que um `User` (Django Auth) é criado, o receptor `create_user_profile` instacia automaticamente o `UsuarioProfile` correspondente. Isso previne erros de `DoesNotExist` ao acessar o perfil em outras partes do sistema.

## 4. Métricas Individuais (`KpiRegistroMensal`)
Este modelo armazena os snapshots de performance do usuário.
- É alimentado pelo app `kpis`.
- Serve como base para o dashboard de performance individual no painel principal.

## 5. Administração Customizada
O arquivo `admin.py` implementa uma interface personalizada que:
- Exibe o perfil inline na edição do usuário.
- Filtra a lista de usuários por país e setor.
- Fornece links rápidos para as atividades do usuário no Odoo.
