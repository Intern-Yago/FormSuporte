from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import UsuarioProfile

User = get_user_model()

@receiver(post_save, sender=User)
def criar_ou_salvar_perfil_usuario(sender, instance, created, **kwargs):
    """
    Sempre que um usuário for criado no Django, cria automaticamente
    um UsuarioProfile em branco para ele.
    """
    if created:
        UsuarioProfile.objects.create(user=instance)
    else:
        # Fallback caso o usuário já exista mas ainda não tenha perfil
        UsuarioProfile.objects.get_or_create(user=instance)