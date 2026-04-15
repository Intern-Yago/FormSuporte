from django.contrib.auth import get_user_model

def check_user_full_permission(user):
    """
    Acesso total ao sistema de ocorrências:
    - superuser
    - dono, diretor
    - qualquer cargo do setor TI
    - gestor do setor SUPORTE
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    profile = getattr(user, 'profile', None)
    if not profile:
        return False

    # Acesso total para cargos de liderança
    if profile.role in ['dono', 'diretor']:
        return True

    # Acesso total para o setor de TI (independente do cargo)
    if profile.setor == 'ti':
        return True

    # Gestores do suporte também têm acesso total
    if profile.role == 'gestor' and profile.setor == 'suporte':
        return True

    return False
