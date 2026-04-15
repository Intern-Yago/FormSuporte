from django.urls import re_path
from . import consumers, notification_consumers

websocket_urlpatterns = [
    re_path(r'ws/chat/(?P<record_id>\w+)/$', consumers.ChatConsumer.as_asgi()),
    re_path(r'ws/notifications/$', notification_consumers.NotificationConsumer.as_asgi()),
]
