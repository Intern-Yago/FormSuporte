from django.apps import AppConfig


class SituacaoVeiculoConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'situacao_veiculo'
    verbose_name= 'Verificar suporte'

    def ready(self):
        import situacao_veiculo.signals