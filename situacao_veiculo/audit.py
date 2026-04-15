# situacao_veiculo/audit.py
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import force_str

def admin_log(user, obj, action_flag=CHANGE, message=""):
    """
    Escreve no django_admin_log (LogEntry) para aparecer em:
    - 'Ações recentes'
    - histórico dentro do User (inline)
    """
    if not user or not getattr(user, "is_authenticated", False):
        return

    ct = ContentType.objects.get_for_model(obj.__class__)
    LogEntry.objects.log_action(
        user_id=user.pk,
        content_type_id=ct.pk,
        object_id=obj.pk,
        object_repr=force_str(obj)[:200],
        action_flag=action_flag,    
        change_message=message or "",
    )
