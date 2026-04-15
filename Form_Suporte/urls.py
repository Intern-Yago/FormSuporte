from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
import situacao_veiculo.views as situacao_views

urlpatterns = [
    # URLs sem prefixo de idioma
    path('admin/', admin.site.urls),

    path("painel/", include("painel.urls")),
    path("simulador/", include("simulador.urls")),
    path("api/", include("API.urls")),
    path("form/", include("form.urls")),
    path("seriais/", include("serial_vci.urls")),
    path("pedido/", include("pedido.urls")),
    path("webhooks/situacao/equipment-status/", situacao_views.webhook_equipment_status, name="webhook_equipment_status"),
    path("clientes/", include("clientes.urls", namespace="clientes")),
    path("kpis/", include("kpis.urls", namespace="kpis")),

    # URL para trocar idioma
    path('i18n/', include('django.conf.urls.i18n')),
]


# URLs que você quer que tenham prefixo de idioma
urlpatterns += i18n_patterns(
    path("", include("ocorrencia_erro.urls")),
    path("situacao/", include("situacao_veiculo.urls")),
)


# Arquivos estáticos E DE MÍDIA no modo DEBUG
if settings.DEBUG:
    # Já estava: Servindo arquivos estáticos
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # NOVO: Servindo arquivos de mídia (imagens do SerialFoto)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 