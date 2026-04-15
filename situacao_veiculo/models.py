# models.py
from django.db import models
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.core.exceptions import ValidationError
from datetime import date
from django.conf import settings

class SerialSearchLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="serial_searches",
        verbose_name="Usuário",
        null=True
    )

    searched_serial = models.CharField(
        "Serial digitado",
        max_length=120,
        db_index=True
    )

    resolved_serial = models.CharField(
        "Serial principal resolvido",
        max_length=120,
        blank=True,
        default=""
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} pesquisou {self.searched_serial} em {self.created_at:%d/%m/%Y %H:%M}"


class Cliente(models.Model):
    data = models.DateField(verbose_name="Data", blank=False, default=timezone.now)
    vencimento = models.DateField(verbose_name="Vencimento", blank=True, null=True)
    anos_para_vencimento = models.PositiveIntegerField(
        verbose_name="Anos para vencimento",
        default=2,
        help_text="Quantidade de anos até o vencimento."
    )

    serial = models.CharField(verbose_name="Serial", max_length=100, blank=True, default='')
    serial_sec = models.CharField(verbose_name="Serial Secundário", max_length=100, blank=True, default='')
    email = models.EmailField(verbose_name="E-mail", max_length=255, blank=True, null=True)

    nome = models.CharField(verbose_name="Nome", max_length=100, blank=True, null=True)
    cnpj = models.CharField(max_length=30, verbose_name='CPF/CNPJ', blank=True, default="SEM DADO", null=True)
    tel = models.CharField(max_length=100, verbose_name='Telefone', blank=True, default="SEM DADO", null=True)
    equipamento = models.CharField(verbose_name='Equipamento', max_length=100, blank=True, default="", null=True)

    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Cadastrado por",
        related_name="clientes_criados"
    )

    # ====== Campos vindos do BlockUnblock (webhook) ======
    equipment_status = models.CharField(
        "Status do equipamento (BlockUnblock)",
        max_length=30,
        blank=True,
        null=True,
        help_text="Ex.: BLOCKED/UNBLOCKED/etc."
    )

    equipment_reason = models.CharField(
        "Motivo do bloqueio (BlockUnblock)",
        max_length=255,
        blank=True,
        null=True
    )

    equipment_blocked_by = models.CharField(
        "Bloqueado por (ID externo)",
        max_length=120,
        blank=True,
        null=True,
        help_text="ID do usuário no sistema BlockUnblock (ex.: u-123)"
    )

    equipment_last_update = models.DateTimeField(
        "Última atualização do status (BlockUnblock)",
        blank=True,
        null=True
    )

    last_webhook_event = models.CharField(
        "Último evento recebido (webhook)",
        max_length=60,
        blank=True,
        null=True
    )

    updated_at = models.DateTimeField(
        "Atualizado em",
        auto_now=True,
        help_text="Data/hora da última atualização deste cadastro."
    )

    updated_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Atualizado por",
        related_name="clientes_atualizados"
    )

    contactado = models.BooleanField(
        "Contactado (último atendimento realizado)",
        default=False,
        help_text="Quando o serial estiver BLOCKED, muda a mensagem exibida."
    )

    status_message_custom = models.CharField(
        "Mensagem de status (curta) - personalizada",
        max_length=200,
        blank=True,
        null=True,
        help_text="Se preenchido, sobrescreve a mensagem padrão."
    )

    mensagem = models.TextField(
        "Mensagem (detalhada)",
        blank=True,
        null=True,
        help_text="Mensagem descritiva exibida quando existir."
    )

    def has_custom_message(self):
        return bool(self.status_message_custom or self.mensagem)

    has_custom_message.boolean = True
    has_custom_message.short_description = "Msg personalizada?"

    def clean(self):
        if self.serial:
            qs = Cliente.objects.filter(serial__iexact=self.serial)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({'serial': 'Este serial já está cadastrado para outro cliente.'})

    def save(self, *args, **kwargs):
        if isinstance(self.serial, str):
            self.serial = self.serial.strip()
        if isinstance(self.serial_sec, str):
            self.serial_sec = self.serial_sec.strip()

        if not self.vencimento and self.data and self.anos_para_vencimento:
            self.vencimento = self.data + relativedelta(years=self.anos_para_vencimento)

        # ✅ REGRA: se suporte estiver LIBERADO (direito), zera contactado
        if self.vencimento:
            dias = (self.vencimento - date.today()).days
            if dias > 30:  # direito
                self.contactado = False

        super().save(*args, **kwargs)

    def __str__(self):
        serial = (self.serial or "").strip()
        nome = (self.nome or "").strip()
        if serial and nome:
            return f"{nome} - {serial}"
        return nome or serial or f"Cliente #{self.pk}"

    @property
    def _vencimento_dias(self):
        if not self.vencimento:
            return -999999
        return (self.vencimento - date.today()).days

    @property
    def status(self):
        # ✅ prioridade: webhook (BlockUnblock)
        equip_status = (self.equipment_status or "").strip().upper()
        if equip_status == "BLOCKED":
            return "bloqueado"

        if not self.vencimento:
            return 'indefinido'
        if self.data and self.vencimento < self.data:
            return 'bloqueado_data_invalida'
        dias = self._vencimento_dias
        if dias > 30:
            return 'direito'
        elif dias < 1:
            return 'vencido'
        else:
            return 'vencendo'

    @property
    def status_message_default(self):
        s = self.status
        if s == 'bloqueado':
            return "BLOQUEADO - FALTA DE PAGAMENTO"
        if s == 'direito':
            return "SUPORTE LIBERADO - Atender normalmente"
        elif s == 'vencido':
            return "SUPORTE VENCIDO - Não fazer atendimento - BLOQUEADO"
        elif s == 'vencendo':
            return "SUPORTE A VENCER - Atender normalmente - Passar para o comercial"
        elif s == 'bloqueado_data_invalida':
            return "Não fazer atendimento - INFORMAR AO GESTOR"
        else:
            return "Consultar ativação - ATUALIZAR DADOS."

    @property
    def status_message(self):
        # 1. Dá prioridade MÁXIMA para a mensagem curta personalizada do Admin
        if self.status_message_custom:
            return self.status_message_custom

        s = self.status

        # 2. Se não tem custom, segue o fluxo normal
        if s == "bloqueado":
            return "BLOQUEADO - FALTA DE PAGAMENTO"

        if s == "vencido":
            if self.contactado:
                return "Suporte vencido - não fazer atendimento - BLOQUEADO"
            return "Suporte vencido - último atendimento"

        if s in {"bloqueado_data_invalida"}:
            return self.status_message_default

        return self.status_message_default

    @property
    def message_effective(self):
        # 1. Dá prioridade MÁXIMA para a mensagem detalhada do Admin
        if self.mensagem:
            return self.mensagem

        s = self.status

        # 2. Se não tem custom, segue o fluxo normal
        if s == "bloqueado":
            if self.equipment_last_update:
                d = timezone.localtime(self.equipment_last_update).date()
            else:
                d = self.data or timezone.localdate()
            return f"Contactar financeiro - bloqueado em {d.strftime('%d/%m/%Y')}"

        if s == "vencido":
            if self.contactado:
                return "Suporte vencido - não fazer atendimento - BLOQUEADO"
            return "Suporte vencido - último atendimento"

        if s in {"bloqueado_data_invalida"}:
            return self.status_message_default

        return self.status_message_default