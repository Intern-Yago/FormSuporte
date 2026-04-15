# pedido/urls.py
from django.urls import path
from . import views

app_name = "pedido"

urlpatterns = [
    path("", views.index, name="index"),

    path("api/buscar-registros/", views.api_buscar_registros, name="api_buscar_registros"),
    path("api/lookup/", views.lookup_cliente_e_registro, name="lookup_cliente_e_registro"),

    # ODOO TESTE
    path("api/odoo/testar-cliente/", views.api_odoo_testar_cliente, name="api_odoo_testar_cliente"),

    # criar venda a partir do registro
    path("abrir/<int:registro_id>/", views.abrir_registro_no_painel, name="abrir_registro"),

    path("api/cliente/<int:cliente_id>/salvar/", views.api_salvar_cliente, name="api_salvar_cliente"),
    path("api/cliente/<int:cliente_id>/enderecos/", views.api_listar_enderecos_cliente, name="api_listar_enderecos_cliente"),
    path("api/cliente/<int:cliente_id>/enderecos/salvar/", views.api_salvar_endereco_cliente, name="api_salvar_endereco_cliente"),

    path("pagamento/cartao/<str:token>/", views.pagina_pagamento_cartao, name="pagina_pagamento_cartao"),
    path(
        "api/pagamento/cartao/<str:token>/pagar/",
        views.api_pagamento_cartao_pagar,
        name="api_pagamento_cartao_pagar"
        ),
    path(
        "3ds/s/<int:venda_id>/", 
        views.three_d_secure_success,
        name="three_d_secure_success",
    ),
    path(
        "3ds/f/<int:venda_id>/",
        views.three_d_secure_failure,
        name="three_d_secure_failure",
    ),
    path(
        "3ds/c/<int:venda_id>/",
        views.three_d_secure_callback,
        name="three_d_secure_callback",
    ),
    path("pagamento/pix/<str:token>/", views.pagina_pagamento_pix, name="pagina_pagamento_pix"),
    path(
        "api/pagamento/pix/<str:token>/gerar/",
        views.api_pagamento_pix_gerar_qrcode,
        name="api_pagamento_pix_gerar_qrcode",
    ),
    path(
        "api/pagamento/pix/<str:token>/consultar/",
        views.api_pagamento_pix_consultar,
        name="api_pagamento_pix_consultar",
    ),
    path(
        "api/pagamento/pix/notificacao/",
        views.api_pagamento_pix_notificacao,
        name="api_pagamento_pix_notificacao",
    ),
]