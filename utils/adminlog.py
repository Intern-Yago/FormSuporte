import re
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.contrib.contenttypes.models import ContentType

def sanitize_message(message: str) -> str:
    """
    Remove padrões de CPF e CNPJ da mensagem para proteger dados sensíveis.
    """
    if not message:
        return ""
    # Padrão para CPF e CNPJ
    cpf_pattern = r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b'
    cnpj_pattern = r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b'

    sanitized = re.sub(cpf_pattern, '[SENSITIVE_DATA]', message)
    sanitized = re.sub(cnpj_pattern, '[SENSITIVE_DATA]', sanitized)
    return sanitized

def add_admin_log(user, obj, message: str, action_flag=CHANGE):
    """
    Registra um log no Admin (LogEntry) com mensagem sanitizada.
    """
    try:
        sanitized_message = sanitize_message(message)
        ct = ContentType.objects.get_for_model(obj.__class__)
        LogEntry.objects.log_action(
            user_id=user.pk if user and getattr(user, "pk", None) else None,
            content_type_id=ct.pk,
            object_id=obj.pk,
            object_repr=str(obj),
            action_flag=action_flag,
            change_message=sanitized_message or "",
        )
    except Exception:
        pass