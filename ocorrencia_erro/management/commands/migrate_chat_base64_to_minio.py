import base64
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from ocorrencia_erro.models import ChatMessage

class Command(BaseCommand):
    help = "Migra imagens de chat salvas em base64 no DB para MinIO (ChatMessage.image)."

    def handle(self, *args, **options):
        qs = ChatMessage.objects.filter(image_base64__isnull=False).exclude(image_base64="")

        total = qs.count()
        self.stdout.write(self.style.WARNING(f"Encontradas {total} mensagens com base64."))

        done = 0
        for m in qs.iterator(chunk_size=200):
            # se já tem image, só limpa base64 (opcional)
            if getattr(m, "image", None) and m.image:
                m.image_base64 = ""
                m.save(update_fields=["image_base64"])
                done += 1
                continue

            b64 = (m.image_base64 or "").strip()
            if not b64:
                continue

            try:
                ext = "png"
                if ";base64," in b64:
                    header, b64data = b64.split(";base64,", 1)
                    if header.startswith("data:image/"):
                        ext_guess = header.split("data:image/")[1].split(";")[0].strip()
                        if ext_guess:
                            ext = ext_guess.lower()
                else:
                    b64data = b64

                raw = base64.b64decode(b64data)

                filename = (m.image_name or f"chat_{m.record_id}.{ext}").strip()
                if not filename.lower().endswith(f".{ext}"):
                    filename = f"{filename}.{ext}"

                m.image.save(filename, ContentFile(raw), save=False)

                # limpa legado
                m.image_base64 = ""
                m.image_type = ""
                # mantém image_name se quiser
                m.save(update_fields=["image", "image_base64", "image_type", "image_name"])

                done += 1
                if done % 100 == 0:
                    self.stdout.write(f"✅ Migradas {done}/{total}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Falha id={m.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Finalizado. Migradas/ajustadas: {done}/{total}"))
