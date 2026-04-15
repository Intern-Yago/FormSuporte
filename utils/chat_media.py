import base64
import io
from PIL import Image
from django.core.files.base import ContentFile

def base64_to_contentfile(data_url: str, fallback_name: str = "chat-image"):
    """
    Recebe string base64 (pode ser dataURL ou puro base64) e devolve ContentFile.
    """
    if not data_url:
        return None, None

    # data:image/png;base64,xxxxx
    if ";base64," in data_url:
        header, b64 = data_url.split(";base64,", 1)
        mime = header.split(":", 1)[1] if ":" in header else None
    else:
        b64 = data_url
        mime = None

    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None, None

    ext = None
    if mime and "/" in mime:
        ext = mime.split("/")[-1].lower()

    if not ext:
        try:
            img = Image.open(io.BytesIO(raw))
            ext = img.format.lower() if img.format else "png"
        except Exception:
            ext = "png"

    filename = f"{fallback_name}.{ext}"
    return ContentFile(raw, name=filename), mime
