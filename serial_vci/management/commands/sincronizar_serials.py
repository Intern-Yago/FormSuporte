from django.core.management.base import BaseCommand
from serial_vci.models import SerialVCI
from situacao_veiculo.models import Cliente

class Command(BaseCommand):
    help = "Sincroniza SerialVCI com Cliente (insere e atualiza)"

    def handle(self, *args, **options):

        criados = 0
        atualizados = 0

        for cli in Cliente.objects.all():

            serial, created = SerialVCI.objects.get_or_create(
                numero_vci=cli.serial,
                defaults={
                    "data": cli.data,        # <- AGORA SALVA SEMPRE NA CRIAÇÃO
                    "cliente": cli.nome,
                    "telefone": cli.tel,
                    "email": "",
                    "pedido": "",
                    "numero_tablet": "",
                    "numero_prog": "",
                }
            )

            if created:
                criados += 1
            else:
                # 🔥 AGORA ATUALIZA A DATA TAMBÉM
                serial.cliente = cli.nome
                serial.telefone = cli.tel
                serial.data = cli.data   # <--------------- ESSENCIAL
                serial.save()
                atualizados += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Sincronização completa! Criados: {criados}, Atualizados: {atualizados}"
            )
        )
