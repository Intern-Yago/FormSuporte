from channels.generic.websocket import AsyncWebsocketConsumer
import json

class SerialVCIConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.group_name = "serial_vci_updates"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass  # Não recebe nada do cliente

    async def enviar_update(self, event):
        await self.send(text_data=json.dumps(event["content"]))
