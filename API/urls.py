# urls.py - Definições de Rotas (URLs) para o App 'API'

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from rest_framework.authtoken.views import obtain_auth_token

# Cria um roteador para as ViewSets do Django REST Framework
router = DefaultRouter()
# Rota para listar e recuperar equipamentos
router.register(r'equipamentos', views.EquipamentosViewSet)
# Rota para listar e recuperar tipos de equipamento
router.register(r'tiposEquipamento', views.TipoEquipamentoViewSet)
# Rota para listar e recuperar marcas de equipamento
router.register(r'marcasEquipamento', views.MarcaEquipamentoViewSet)
# Removemos a rota de listagem GET para clientes; usaremos POST dedicado abaixo
# (router.register(r'clientes', views.ClienteViewSet))

urlpatterns = [
    # Rotas específicas PRIMEIRO
    path('clientes/search/', views.cliente_search, name='cliente_search'),
    path('clientes/buscar/', views.cliente_by_doc, name='cliente_by_doc'),
    path('clientes/cpf_cnpj=<str:cpf_cnpj>', views.cliente_by_doc, name='cliente_by_doc_direct'),
    path('clientes/cpf_cnpj=<str:cpf_cnpj>/', views.cliente_by_doc, name='cliente_by_doc_direct_slash'),

    # Inclui as rotas geradas pelo roteador
    path('', include(router.urls)),
    
    # Rota específica para a geração de PDF (usando @api_view)
    path('generate-pdf/', views.generate_pdf, name='generate_pdf'),
    # Endpoint para obter token (POST with username/password)
    path('api-token-auth/', obtain_auth_token, name='api_token_auth'),
    # Adicione esta linha junto com as outras URLs da sua API
    path('registros/<int:pk>/atualizar/', views.update_registro, name='update_registro'),
    path('registros/<int:pk>/pdf/', views.baixar_pdf_registro, name='baixar_pdf_registro'),
]