import re
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType

def sanitize_message(message: str) -> str:
    """
    Remove padrões de CPF e CNPJ da mensagem para proteger dados sensíveis.
    """
    if not message:
        return ""
    # Padrão para CPF: 000.000.000-00 ou 00000000000
    cpf_pattern = r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b'
    # Padrão para CNPJ: 00.000.000/0000-00 ou 00000000000000
    cnpj_pattern = r'\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b'

    sanitized = re.sub(cpf_pattern, '[SENSITIVE_DATA]', message)
    sanitized = re.sub(cnpj_pattern, '[SENSITIVE_DATA]', sanitized)
    return sanitized

def add_admin_log(user, obj, message: str):
    """
    Cria entrada em Admin > Entradas de log com mensagem sanitizada.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return

    sanitized_message = sanitize_message(message)
    ct = ContentType.objects.get_for_model(obj.__class__)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=ct.pk,
        object_id=str(obj.pk),
        object_repr=str(obj)[:200],
        action_flag=CHANGE,
        change_message=sanitized_message[:2000],
    )