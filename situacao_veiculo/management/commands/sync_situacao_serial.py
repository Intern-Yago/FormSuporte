from django.core.management.base import BaseCommand
from situacao_veiculo.services.odoo_sync import sync_odoo_to_clientes


class Command(BaseCommand):
    help = "Sincroniza situação de serial (Clientes) com Odoo. Use em crontab/Task Scheduler."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-rows",
            type=int,
            default=None,
            help="Limite opcional de linhas do Odoo para processar nesta execução",
        )

    def handle(self, *args, **options):
        max_rows = options.get("max_rows")
        stats = sync_odoo_to_clientes(max_rows=max_rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Odoo sync finalizado: fetched={stats.get('fetched')} created={stats.get('created')} updated={stats.get('updated')} skipped={stats.get('skipped')}"
            )
        )
