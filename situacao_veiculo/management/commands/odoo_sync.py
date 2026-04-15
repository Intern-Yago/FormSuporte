from django.core.management.base import BaseCommand, CommandParser
from situacao_veiculo.services.odoo_sync import sync_odoo_to_clientes

class Command(BaseCommand):
    help = "Sincroniza movimentações de saída do Odoo para Clientes (situacao_veiculo)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('--limit', type=int, default=None, help='Limite de linhas a buscar (None = ilimitado)')

    def handle(self, *args, **options):
        limit = options.get('limit')
        stats = sync_odoo_to_clientes(max_rows=limit)
        self.stdout.write(self.style.SUCCESS(f"Sync concluído: {stats}"))
