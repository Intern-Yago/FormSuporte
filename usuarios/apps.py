from django.apps import AppConfig

class UsuariosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "usuarios"
    verbose_name = "Usuários"

    def ready(self):
        # Importa os signals quando o app iniciar
        import usuarios.signals