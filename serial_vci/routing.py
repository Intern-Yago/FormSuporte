from django.urls import re_path
from .consumers import SerialVCIConsumer

websocket_urlpatterns = [
    re_path(r"ws/seriais/$", SerialVCIConsumer.as_asgi()),
]
