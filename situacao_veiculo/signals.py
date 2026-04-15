from django.db.models.signals import post_save
from django.dispatch import receiver

from situacao_veiculo.models import Cliente
from serial_vci.models import SerialVCI


@receiver(post_save, sender=Cliente)
def sincronizar_serial(sender, instance, **kwargs):

    serial, created = SerialVCI.objects.get_or_create(
        numero_vci=instance.serial,
        defaults={
            "data": instance.data,
            "cliente": instance.nome,
            "telefone": instance.tel,
            "email": "",
            "pedido": "",
            "numero_tablet": "",
            "numero_prog": "",
        }
    )

    if not created:
        serial.cliente = instance.nome
        serial.telefone = instance.tel
        serial.data = instance.data  # <- agora atualiza a data também
        serial.save()
