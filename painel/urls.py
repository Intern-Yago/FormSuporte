from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='painel_home'),
    path('dashboard/', views.dashboard, name='painel_dashboard'),
    path('settings/', views.settings_view, name='painel_settings'),
    path('users/new/', views.user_create, name='painel_user_create'),

    # ✅ NOVO: gestor gerencia colaboradores do próprio setor
    path('users/manage/', views.user_manage, name='painel_user_manage'),
    path('users/<int:user_id>/delete/', views.user_delete, name='painel_user_delete'),
    path('users/<int:user_id>/password/', views.user_set_password, name='painel_user_set_password'),
    path('users/<int:user_id>/update/', views.user_update, name='painel_user_update'),
    path('users/<int:user_id>/systems/', views.user_update_systems, name='painel_user_update_systems'),
    path('users/<int:user_id>/dashboard/', views.user_dashboard_stats, name='painel_user_dashboard_stats'),

    path('logout/', views.sair, name='painel_logout'),
    path("sso/blockunblock/", views.sso_blockunblock, name="sso_blockunblock"),
]
