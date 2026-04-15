from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('buscar/', views.buscar_serial, name='buscar_serial'),
    path('cadastrar/', views.cadastrar_serial, name='cadastrar_serial'),
    path('importar-excel/', views.importar_excel, name='importar_excel'),
    path('api/cliente', views.api_buscar_cliente, name='api_buscar_cliente'),
    path('api/cliente/update', views.api_atualizar_cliente, name='api_atualizar_cliente'),
    path('api/equipamentos-suggest', views.equipamentos_suggest, name='equipamentos_suggest'),
    path('odoo/sync', views.odoo_sync, name='odoo_sync'),
    path("contactado", views.marcar_contactado, name="marcar_contactado"),

    # ==== API usada pelo popup de atualização ====
]
