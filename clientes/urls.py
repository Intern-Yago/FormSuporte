from django.urls import path
from . import views

app_name = "clientes"

urlpatterns = [
    path("", views.painel_clientes, name="painel"),
    path("<int:cliente_id>/", views.detalhe_cliente, name="detalhe"),
    path("<int:cliente_id>/sync-odoo/", views.sync_odoo_cliente, name="sync_odoo"),
    path("sync-all-odoo/", views.sync_all_to_odoo, name="sync_all_odoo"),
    path("sync-shopify/", views.sync_shopify_clientes, name="sync_shopify"),
    path("webhook/shopify/", views.shopify_webhook, name="shopify_webhook"),
    path("<int:cliente_id>/enrich-cnpj/", views.enrich_cliente_api, name="enrich_cnpj"),
    path("orcamento/<int:orcamento_id>/delete/", views.delete_orcamento, name="delete_orcamento"),
    path("ajax/shopify-orders/", views.ajax_load_shopify_orders, name="ajax_shopify_orders"),
]
