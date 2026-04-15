import json
import base64
import re
import io
from PIL import Image

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.files.base import ContentFile

from .models import ChatMessage, Record
from ocorrencia_erro.utils.adminlog import add_admin_log # 👇 Importação do Log

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.record_id = self.scope["url_route"]["kwargs"]["record_id"]
        user = self.scope.get("user")

        # 🔴 SEGURANÇA: Valida se o usuário está autenticado e tem acesso ao Record
        if not user or user.is_anonymous:
            await self.close()
            return

        has_access = await self.check_record_access(user, self.record_id)
        if not has_access:
            await self.close()
            return

        self.room_group_name = f"chat_{self.record_id}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

        # Envia histórico (SEM base64)
        history = await self.get_chat_history()
        for msg in history:
            await self.send(text_data=json.dumps(msg))

    @sync_to_async
    def check_record_access(self, user, record_id):
        """
        Verifica se o usuário tem permissão para ver/interagir com a ocorrência.
        Regra: Superuser, autor da ocorrência ou membros do setor de destino/origem.
        """
        try:
            record = Record.objects.get(id=record_id)
            if user.is_superuser:
                return True
            
            # Se for o autor da ocorrência
            if getattr(record, 'user', None) == user:
                return True
            
            # Se pertencer ao setor de suporte (ou setor de destino da ocorrência)
            user_profile = getattr(user, 'profile', None)
            if user_profile and (user_profile.setor == 'suporte' or user_profile.setor == getattr(record, 'setor_destino', '')):
                return True
                
            return False
        except Record.DoesNotExist:
            return False

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data or "{}")
        action = data.get("action", "new_message")

        # 👇 Redireciona para a edição se for a ação correta
        if action == "edit":
            await self.handle_edit_message(data)
            return

        # ==========================================
        # LÓGICA PADRÃO DE NOVA MENSAGEM
        # ==========================================
        message_text = (data.get("message") or "").strip()

        image_base64 = data.get("image_base64") or ""
        image_type = data.get("image_type") or ""
        image_name = data.get("image_name") or ""

        user = self.scope.get("user")
        if not user or user.is_anonymous:
            return

        record = await sync_to_async(Record.objects.get)(id=self.record_id)

        msg = ChatMessage(
            record=record,
            author=user,
            message=message_text,
        )

        if image_base64:
            await self.apply_base64_to_imagefield(
                msg=msg,
                image_base64=image_base64,
                image_type=image_type,
                image_name=image_name,
            )
            if hasattr(msg, "image_base64"): msg.image_base64 = ""
            if hasattr(msg, "image_type"): msg.image_type = ""
            if hasattr(msg, "image_name"): msg.image_name = image_name or msg.image_name or ""

        await sync_to_async(msg.save)()
        await self.try_update_solution(message_text)

        payload = {
            "action": "new_message",
            "id": msg.id, # 👈 O FRONTEND PRECISA DESSE ID PARA O BOTÃO DE EDITAR
            "message": msg.message,
            "author": user.username,
            "timestamp": msg.timestamp.isoformat(),
            "image_url": (msg.image.url if getattr(msg, "image", None) else ""),
            "image_name": (getattr(msg, "image_name", "") or ""),
            "is_edited": getattr(msg, "is_edited", False),
        }

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "chat_message", "payload": payload},
        )

    # 👇 NOVA FUNÇÃO DE EDIÇÃO E LOG NO ADMIN 👇
    async def handle_edit_message(self, data):
        msg_id = data.get('msg_id')
        new_text = data.get('new_text')
        user = self.scope.get("user")

        if not msg_id or not new_text or not user or user.is_anonymous:
            return

        # 1. Atualiza banco e gera log
        success = await self.update_message_in_db(msg_id, new_text, user)
        
        if success:
            # 2. Reenvia a edição para todos na sala
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message_edit',
                    'msg_id': msg_id,
                    'new_text': new_text
                }
            )

    @sync_to_async
    def update_message_in_db(self, msg_id, new_text, user):
        try:
            msg = ChatMessage.objects.get(id=msg_id, author=user)
            old_text = msg.message
            
            msg.message = new_text
            
            if hasattr(msg, 'is_edited'):
                msg.is_edited = True
                msg.save(update_fields=['message', 'is_edited'])
            else:
                msg.save(update_fields=['message'])

            # Log no Admin
            log_message = f"{user.username} editou mensagem da ocorrencia {msg.record.id}. '{old_text}' -> '{new_text}'"
            add_admin_log(user, msg.record, log_message)
            
            # 🔥 MÁGICA DA SOLUÇÃO SINCRONIZADA 🔥
            sol_pattern = re.compile(r"(?i)solu[cç][aã]o\s*[:\-]\s*(.+)")
            m_new = sol_pattern.search(new_text)
            m_old = sol_pattern.search(old_text)
            
            if m_new:
                # Se ele manteve a palavra "Solução:", salvamos apenas o que vem depois dela
                msg.record.solution = m_new.group(1).strip()
                msg.record.save(update_fields=['solution'])
            elif m_old and not m_new:
                # Se a mensagem antiga tinha "Solução:" e a nova não tem (ele apagou sem querer o prefixo),
                # assumimos que o novo texto inteiro é a nova solução para não dessincronizar o banco!
                msg.record.solution = new_text.strip()
                msg.record.save(update_fields=['solution'])
            
            return True
        except ChatMessage.DoesNotExist:
            return False
        
    async def chat_message_edit(self, event):
        await self.send(text_data=json.dumps({
            'action': 'edit',
            'msg_id': event['msg_id'],
            'new_text': event['new_text']
        }))

    async def chat_message(self, event):
        payload = event.get("payload") or {}
        await self.send(text_data=json.dumps(payload))

    @sync_to_async
    def get_chat_history(self):
        qs = (
            ChatMessage.objects
            .filter(record_id=self.record_id)
            .select_related("author")
            .order_by("timestamp")
        )

        out = []
        for m in qs:
            image_url = ""
            try:
                if getattr(m, "image", None): image_url = m.image.url or ""
            except Exception:
                image_url = ""

            out.append({
                "action": "new_message",
                "id": m.id,
                "message": m.message,
                "author": m.author.username,
                "timestamp": m.timestamp.isoformat(),
                "image_url": image_url,
                "image_name": (getattr(m, "image_name", "") or ""),
                "is_edited": getattr(m, "is_edited", False), # 👈 Envia flag de edição no histórico
            })
        return out

    async def apply_base64_to_imagefield(self, msg, image_base64: str, image_type: str, image_name: str):
        try:
            b64 = image_base64.strip()
            if not b64: return
            
            # Decodifica Base64
            if ";base64," in b64:
                header, b64data = b64.split(";base64,", 1)
            else:
                b64data = b64
                
            raw = base64.b64decode(b64data)

            # 🔴 SEGURANÇA: Valida se o conteúdo é uma imagem real
            try:
                img = Image.open(io.BytesIO(raw))
                img.verify() # Verifica se o arquivo está corrompido ou é malicioso
                ext = img.format.lower()
            except Exception:
                # Se não for uma imagem válida, aborta o salvamento
                return

            safe_name = (image_name or f"chat_{self.record_id}.{ext}").strip()
            if "." not in safe_name: safe_name = f"{safe_name}.{ext}"
            
            try:
                if hasattr(msg, "image_name"): msg.image_name = safe_name
                if hasattr(msg, "image_type"): msg.image_type = f"image/{ext}"
            except Exception: pass
            
            msg.image.save(safe_name, ContentFile(raw), save=False)
        except Exception: return

    @sync_to_async
    def try_update_solution(self, message_text: str):
        try:
            if not message_text: return
            sol_pattern = re.compile(r"(?i)solu[cç][aã]o\s*[:\-]\s*(.+)")
            m = sol_pattern.search(message_text)
            if m: Record.objects.filter(id=self.record_id).update(solution=m.group(1).strip())
        except Exception: pass
