# urls.py - Definições de Rotas (URLs) para o App 'form'

from django.urls import path
from . import views

# Lista de padrões de URL para o aplicativo 'form'
urlpatterns = [
    # Rota principal (listagem de veículos)
    path('', views.index, name='index_form'),
    
    # Rota para o cadastro de novos veículos
    path('cadastrar/', views.cadastrar_veiculo, name='cadastrar_veiculo'),
    
    # Rota API para obter opções de filtro dinâmicas (usada via AJAX)
    path('get-opcoes/', views.get_opcoes_filtro, name='get_opcoes_filtro'),
    
    # Rota API para atualização de veículo (versão mais simples)
    path('update-vehicle/', views.update_vehicle, name='update_vehicle'),
    
    # Rota API para atualização de campo específico de veículo (versão mais robusta)
    path('update-field/', views.update_vehicle_field, name='update_field'),
    path('dashboard/', views.dashboard_edicoes, name='dashboard_edicoes'),
]
