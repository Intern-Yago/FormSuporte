from django.urls import path, include

app_name = "kpis"

urlpatterns = [
    # Manda tudo que começar com /suporte/ para as URLs daquele setor
    path("suporte/", include("kpis.setores.suporte.urls")),
    path("comercial/", include("kpis.setores.comercial.urls")),
]