from django.apps import AppConfig


class OcorrenciaErroConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ocorrencia_erro'
    verbose_name = 'Ocorrência de erros'

    def ready(self):
        """
        Este método é executado quando o aplicativo está pronto.
        É o local recomendado para importar os sinais.
        """