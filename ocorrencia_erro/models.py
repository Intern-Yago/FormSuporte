# ocorrencia_erro/models.py
# -*- coding: utf-8 -*-

import os
import uuid
import random
import string

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_delete
from django.dispatch import receiver


# =========================
# Helpers de upload (MinIO)
# =========================

def _safe_name(filename: str) -> str:
    """
    Gera nome único para evitar sobrescrever arquivos com mesmo nome.
    Mantém a extensão.
    """
    _, ext = os.path.splitext(filename or "")
    ext = (ext or "").lower()
    return f"{uuid.uuid4().hex}{ext}"


def upload_painel_record(instance, filename):
    """
    Arquivos vinculados diretamente ao Record (painel).
    Vai para: painel/<record_id>/<YYYY>/<MM>/<uuid>.<ext>
    """
    record_id = getattr(instance, "id", None) or "sem_record"
    return f"painel/{record_id}/{timezone.now().strftime('%Y/%m')}/{_safe_name(filename)}"


def upload_painel_arquivo_ocorrencia(instance, filename):
    """
    Arquivos anexados via ArquivoOcorrencia (painel).
    Vai para: painel/<record_id>/<YYYY>/<MM>/<uuid>.<ext>
    """
    record_id = getattr(instance, "record_id", None) or "sem_record"
    return f"painel/{record_id}/{timezone.now().strftime('%Y/%m')}/{_safe_name(filename)}"


def upload_chat_media(instance, filename):
    """
    Se você ativar FileField/ImageField no ChatMessage (opcional).
    Vai para: chat/<record_id>/<YYYY>/<MM>/<uuid>.<ext>
    """
    record_id = getattr(instance, "record_id", None) or "sem_record"
    return f"chat/{record_id}/{timezone.now().strftime('%Y/%m')}/{_safe_name(filename)}"


def gerar_codigo_espanha():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


# =========================
# Models
# =========================

class Country(models.Model):
    class Meta:
        verbose_name = "País"
        verbose_name_plural = "Países"

    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class Device(models.Model):
    class Meta:
        verbose_name = "Equipamento"
        verbose_name_plural = "Equipamentos"

    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class CountryPermission(models.Model):
    """
    Permissão de países por usuário.
    ⚠️ Fica SOMENTE aqui (ocorrencia_erro). Não duplique em outros apps.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="country_permissions",
    )
    country = models.ForeignKey(Country, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("user", "country")
        verbose_name = "Permissão de País"
        verbose_name_plural = "Permissões de País"

    def __str__(self):
        username = getattr(self.user, "username", "user")
        return f"{username} - {self.country.name}"


class Record(models.Model):
    class STATUS_OCORRENCIA(models.TextChoices):
        DONE = "DONE", "Concluído"
        LATE = "LATE", "Atrasado"
        PROGRESS = "PROGRESS", "Em progresso"
        REQUESTED = "REQUESTED", "Requisitado"
        AWAITING_CHINA = "AWAITING_CHINA", "Aguardando China"
        AWAITING_CHINA_LATE = "AWAITING_CHINA_LATE", "China Atrasada"

    origem_ocorrencia = models.CharField(max_length=30, blank=True, null=True)
    parceiro = models.CharField(max_length=120, blank=True, null=True)

    id = models.AutoField(primary_key=True)

    ticket_fabricante = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        verbose_name="Ticket do Fabricante",
    )

    codigo_externo = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
    )

    data = models.DateField(
        verbose_name="Data de reporte",
        default=timezone.now,
        help_text="Data em que o problema foi reportado",
    )
    deadline = models.DateField(
        verbose_name="Prazo",
        blank=True,
        null=True,
        help_text="Prazo para resolução do problema",
    )
    finished = models.DateField(
        verbose_name="Concluído em",
        blank=True,
        null=True,
        help_text="Data em que o problema foi resolvido",
    )

    # ✅ vai para MinIO
    arquivo = models.FileField(upload_to=upload_painel_record, null=True, blank=True)

    technical = models.CharField(
        max_length=100,
        default="Não identificado",
        verbose_name="Técnico",
    )
    responsible = models.CharField(
        max_length=100,
        default="Não identificado",
        verbose_name="Responsável",
        null=True,
        blank=True,
    )

    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Equipamento",
    )

    area = models.CharField(max_length=20, default="N/A", verbose_name="Área")
    serial = models.CharField(max_length=20, blank=True, null=True, default="N/A", verbose_name="Serial")
    brand = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="Marca")
    model = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="Modelo")
    contact = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="Contato")
    vin = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="VIN")
    year = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="Ano")

    country = models.ForeignKey(Country, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="País")

    tipo_ecu = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tipo de ECU")
    tipo_motor = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tipo de Motor")
    sistema = models.CharField(max_length=150, blank=True, null=True, verbose_name="Sistema")
    tipo_problema = models.CharField(max_length=150, blank=True, null=True, verbose_name="Tipo de Problema")

    country_original = models.CharField(max_length=100, null=True, blank=True, verbose_name="País inicial")
    version = models.CharField(max_length=100, blank=True, null=True, default="N/A", verbose_name="Versão")

    problem_detected = models.TextField(default="Não identificado", verbose_name="Problema detectado")

    status = models.CharField(
        max_length=25,
        choices=STATUS_OCORRENCIA.choices,
        default=STATUS_OCORRENCIA.REQUESTED,
    )

    feedback_technical = models.TextField(blank=True, null=True, default="Não identificado", verbose_name="Feedback Técnico")
    feedback_manager = models.TextField(blank=True, null=True, default="Não identificado", verbose_name="Feedback Manager")
    solution = models.TextField(blank=True, null=True, verbose_name="Solução")
    detalhes_responsavel = models.TextField(blank=True, null=True, default="Não identificado", verbose_name="Detalhes do Responsável")
    tipo_chave = models.TextField(blank=True, null=True, default="Não identificado", verbose_name="Tipo Chave")

    def is_awaiting_china_late(self):
        return (
            self.status == self.STATUS_OCORRENCIA.AWAITING_CHINA
            and self.deadline
            and self.deadline < timezone.now().date()
        )

    def clear_finished_date(self):
        self.finished = None
        self._explicitly_cleared_finished = True
        if self.status == self.STATUS_OCORRENCIA.DONE:
            self.status = self.STATUS_OCORRENCIA.PROGRESS

    def clear_deadline_date(self):
        self.deadline = None
        self._explicitly_cleared_deadline = True
        if self.status != self.STATUS_OCORRENCIA.AWAITING_CHINA:
            self.status = self.STATUS_OCORRENCIA.REQUESTED

    def clean(self):
        super().clean()
        today = timezone.now().date()

        # 0) FINALIZADO -> DONE
        if self.finished:
            self.status = self.STATUS_OCORRENCIA.DONE
            return

        # 1) CHINA PRIORIDADE
        if self.status in [self.STATUS_OCORRENCIA.AWAITING_CHINA, self.STATUS_OCORRENCIA.AWAITING_CHINA_LATE]:
            if self.deadline and self.deadline < today:
                self.status = self.STATUS_OCORRENCIA.AWAITING_CHINA_LATE
            else:
                self.status = self.STATUS_OCORRENCIA.AWAITING_CHINA
            return

        # 2) GERAL
        if not self.finished:
            if self.deadline:
                if (self.deadline - today).days < 0:
                    self.status = self.STATUS_OCORRENCIA.LATE
                elif self.status == self.STATUS_OCORRENCIA.REQUESTED:
                    self.status = self.STATUS_OCORRENCIA.PROGRESS
            elif self.status not in [self.STATUS_OCORRENCIA.PROGRESS, self.STATUS_OCORRENCIA.DONE]:
                self.status = self.STATUS_OCORRENCIA.REQUESTED

        self.area = self.area.upper() if self.area else ""
        self.brand = self.brand.upper() if self.brand else ""
        self.model = self.model.upper() if self.model else ""
        self.technical = self.technical.capitalize() if self.technical else ""

    def save(self, *args, **kwargs):
        if not self.country_original and self.country:
            self.country_original = self.country.name

        self.clean()
        super().save(*args, **kwargs)

        if not self.codigo_externo and "codigo_externo" not in (kwargs.get("update_fields") or []):
            self.codigo_externo = str(self.id)
            super().save(update_fields=["codigo_externo"])


class ArquivoOcorrencia(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="arquivos", null=True)
    arquivo = models.FileField(upload_to=upload_painel_arquivo_ocorrencia)
    nome_original = models.CharField(max_length=255, blank=True)
    data_upload = models.DateTimeField(verbose_name="Data de upload", default=timezone.now)

    def __str__(self):
        rid = self.record_id or "sem_record"
        return f"ArquivoOcorrencia(record={rid}, arquivo={self.arquivo.name})"

    def delete(self, *args, **kwargs):
        storage = self.arquivo.storage if self.arquivo else None
        name = self.arquivo.name if self.arquivo else None

        super().delete(*args, **kwargs)

        if storage and name:
            try:
                storage.delete(name)
            except Exception:
                pass


class Notificacao(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notificacoes",
        verbose_name="Usuário",
    )
    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="notificacoes",
        verbose_name="Ocorrência",
    )
    tipo = models.CharField(
        max_length=20,
        choices=[("feedback_manager", "Feedback do Gestor")],
        default="feedback_manager",
        verbose_name="Tipo de Notificação",
    )
    titulo = models.CharField(max_length=200, verbose_name="Título")
    resumo = models.TextField(max_length=500, verbose_name="Resumo")
    lida = models.BooleanField(default=False, verbose_name="Lida")
    criada_em = models.DateTimeField(auto_now_add=True, verbose_name="Criada em")
    lida_em = models.DateTimeField(null=True, blank=True, verbose_name="Lida em")

    class Meta:
        verbose_name = "Notificação"
        verbose_name_plural = "Notificações"
        ordering = ["-criada_em"]
        indexes = [
            models.Index(fields=["user", "lida"]),
            models.Index(fields=["criada_em"]),
        ]

    def __str__(self):
        username = getattr(self.user, "username", "user")
        return f"Notificação para {username} - {self.titulo}"

    def marcar_como_lida(self):
        if not self.lida:
            self.delete()


class ChatMessage(models.Model):
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="chat_messages")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    message = models.TextField(blank=True)

    is_edited = models.BooleanField(default=False)
    
    image = models.ImageField(upload_to=upload_chat_media, blank=True, null=True)
    file = models.FileField(upload_to=upload_chat_media, blank=True, null=True)

    image_base64 = models.TextField(blank=True, null=True)
    image_type = models.CharField(max_length=50, blank=True, null=True)
    image_name = models.CharField(max_length=255, blank=True, null=True)

    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]


class OptionItem(models.Model):
    AREA_CHOICES = (
        ("IMMO", "IMMO"),
        ("Diagnosis", "Diagnosis"),
        ("Device", "Device"),
        ("BOX360", "BOX360"),
    )
    CATEGORY_CHOICES = (
        ("SISTEMA", "Sistema"),
        ("PROBLEMA", "Tipo de Problema"),
    )

    area = models.CharField(max_length=20, choices=AREA_CHOICES)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    label = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    cod_usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_options",
        verbose_name="Criado por",
    )

    class Meta:
        unique_together = ("area", "category", "label", "parent")
        ordering = ["category", "area", "parent__label", "order", "label"]

    def __str__(self) -> str:
        return f"{self.get_category_display()} / {self.area} - {self.label}"


# =========================
# Signals (bulk delete / cascade safety)
# =========================

@receiver(post_delete, sender=ArquivoOcorrencia)
def arquivo_ocorrencia_post_delete(sender, instance, **kwargs):
    if instance.arquivo and instance.arquivo.name:
        try:
            instance.arquivo.storage.delete(instance.arquivo.name)
        except Exception:
            pass


@receiver(post_delete, sender=Record)
def record_file_post_delete(sender, instance, **kwargs):
    if instance.arquivo and instance.arquivo.name:
        try:
            instance.arquivo.storage.delete(instance.arquivo.name)
        except Exception:
            pass


class RecordStatusLog(models.Model):
    class EventType(models.TextChoices):
        CREATED = "CREATED", "Criada"
        RESPONSIBLE_SET = "RESPONSIBLE_SET", "Responsável definido"
        STATUS = "STATUS", "Mudança de status"
        DEADLINE = "DEADLINE", "Mudança de prazo"
        FINISHED = "FINISHED", "Mudança de concluído"

    record = models.ForeignKey("Record", on_delete=models.CASCADE, related_name="movement_logs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    event_type = models.CharField(max_length=30, choices=EventType.choices, default=EventType.STATUS)

    from_status = models.CharField(max_length=25, blank=True, null=True)
    to_status = models.CharField(max_length=25, blank=True, null=True)

    field = models.CharField(max_length=50, blank=True, null=True)
    note = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "Movimentação"
        verbose_name_plural = "Movimentações"
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["record", "created_at"])]

    def __str__(self):
        rid = self.record_id or "-"
        return f"{rid} {self.event_type} {self.created_at:%d/%m/%Y %H:%M}"