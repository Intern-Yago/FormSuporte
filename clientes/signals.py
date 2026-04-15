from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Cliente
from .services.odoo_sync import ensure_odoo_partner_for_cliente
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Cliente)
def sync_cliente_with_odoo(sender, instance, created, **kwargs):
    """
    Tenta vincular automaticamente o cliente com o Odoo se ele ainda não tiver um odoo_partner_id.
    """
    # Evita recursão infinita se o save vier da própria sincronização
    if kwargs.get('update_fields') and 'odoo_partner_id' in kwargs['update_fields']:
        return

    if not instance.odoo_partner_id:
        try:
            # Tenta encontrar ou criar o parceiro no Odoo usando os identificadores disponíveis
            # (CPF, CNPJ, Email ou Telefone - conforme lógica atualizada em odoo_sync.py)
            ensure_odoo_partner_for_cliente(instance, always_update_local=True)
        except Exception as e:
            # Loga o erro mas não impede o salvamento do cliente
            logger.warning(f"Falha na sincronização automática com Odoo para cliente {instance.id}: {e}")
