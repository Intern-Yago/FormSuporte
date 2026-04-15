# Form_Suporte/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Form_Suporte.settings")

django_asgi_app = get_asgi_application()  # isso já configura settings/apps

import ocorrencia_erro.routing  # só depois

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(ocorrencia_erro.routing.websocket_urlpatterns)
    ),
})
