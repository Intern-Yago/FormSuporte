from django.urls import path, include
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path("ocorrencia", views.index, name="ocorrencia_home"),

    # ================= DASHBOARD =================
    path('dashboard/', views.dashboard_view, name='dashboard_ocorrencias'),
    path('dashboard/detalhes/', views.dashboard_detalhes, name='dashboard_detalhes'),
    path('dashboard/relatorio/', views.gerar_relatorio_dashboard, name='gerar_relatorio_dashboard'),
    # =============================================

    path('subir_ocorrencia/', views.subir_ocorrencia, name='subir_ocorrencia'),
    path('filter_data/', views.filter_data_view, name='filter_data'),
    path('update_ocorrencia/', views.alterar_dados, name='update_ocorrencia'),
    path('options/', views.options_config, name='ocorrencia_options'),
    path('options/add/', views.add_option_item, name='ocorrencia_options_add'),
    path('criar_usuario/', views.criar_usuario, name='criar_usuario'),
    path('login/', views.login_view, name='login_ocorrencias'),
    path('logout/', views.logout_view, name='logout'),

    path('download_arquivo/<int:arquivo_id>/', views.download_arquivo, name='download_arquivo'),
    path('get_record/<int:pk>/', views.get_record, name='get_record'),

    path('notificacoes/', views.listar_notificacoes, name='listar_notificacoes'),
    path('notificacoes/contar/', views.contar_notificacoes_nao_lidas, name='contar_notificacoes'),
    path('notificacoes/<int:notificacao_id>/marcar_lida/', views.marcar_notificacao_lida, name='marcar_notificacao_lida'),
    path('notificacoes/record/<int:record_id>/marcar_lidas/', views.marcar_notificacoes_por_record_como_lidas, name='marcar_notificacoes_record_lidas'),

    path("traduzir/", views.traduzir_api, name="traduzir_api"),

    path('gerar_pdf/<int:record_id>/', views.gerar_pdf_ocorrencia, name='gerar_pdf_ocorrencia_get'),
    path('gerar_pdf/', views.gerar_pdf_ocorrencia, name='gerar_pdf_ocorrencia_post'),

    path("ocorrencia/download_todos/<int:record_id>/", views.download_todos_arquivos, name="download_todos_arquivos"),
    path('clonar_ocorrencia/', views.clonar_ocorrencia, name='clonar_ocorrencia'),
    path("chat/<int:record_id>/upload-image/", views.upload_chat_image, name="upload_chat_image"),
    path("chat/edit_message/", views.edit_chat_message, name="edit_chat_message"),
    path('i18n/', include('django.conf.urls.i18n')),
]
