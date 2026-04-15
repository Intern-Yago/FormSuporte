from django.core.management.base import BaseCommand
from clientes.services.shopify_sync import ShopifySyncService
import time

class Command(BaseCommand):
    help = 'Sincroniza todos os clientes do Shopify para o banco de dados local'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Iniciando sincronização completa do Shopify...'))
        start_time = time.time()
        
        try:
            service = ShopifySyncService()
            # Podemos passar um logger ou apenas imprimir no terminal
            count = service.sync_all_customers()
            
            duration = time.time() - start_time
            self.stdout.write(self.style.SUCCESS(
                f'Sucesso! {count} clientes processados em {duration:.2f} segundos.'
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Erro durante a sincronização: {e}'))
