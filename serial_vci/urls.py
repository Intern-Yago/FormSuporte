from django.urls import path
from . import views

urlpatterns = [
    path("", views.lista_seriais, name="lista_seriais"),
    path("adicionar/", views.adicionar_serial, name="adicionar_serial"),
    path("detalhes/<int:serial_id>/", views.detalhes_serial, name="detalhes_serial"),
    path("editar/<int:serial_id>/", views.editar_serial, name="editar_serial"), # NOVO
    path("remover_foto/<int:foto_id>/", views.remover_foto, name="remover_foto"), # NOVO
    path('<int:serial_id>/garantia/add/', views.add_garantia, name='add_garantia'),
    path("garantia/<int:garantia_id>/", views.garantia_detalhes, name="garantia_detalhes"),
    path("garantia/<int:garantia_id>/add_comentario/", views.add_comentario, name="add_comentario"),
    path("garantia/<int:garantia_id>/delete/", views.deletar_garantia, name="deletar_garantia"),
    path("comentario/<int:comentario_id>/delete/", views.delete_comentario, name="delete_comentario")

]