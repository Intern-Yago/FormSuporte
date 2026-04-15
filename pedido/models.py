from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from decimal import Decimal
import os
import re
import unicodedata

from simulador.models import Registro


def _sanitize_filename(filename: str, max_len: int = 120) -> str:
    if not filename:
        return "arquivo"

    base, ext = os.path.splitext(filename)

    nfkd = unicodedata.normalize("NFKD", base)
    base = "".join(c for c in nfkd if ord(c) < 128)

    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    base = re.sub(r"_+", "_", base)

    if not base:
        base = "arquivo"

    if len(base) > max_len:
        base = base[:max_len].rstrip("._-")

    ext = (ext or "").lower()
    if len(ext) > 10:
        ext = ""

    return f"{base}{ext}"


def upload_venda_path(instance, filename):
    safe_name = _sanitize_filename(filename)
    return f"pedido/venda_{instance.venda_id}/{safe_name}"


class Venda(models.Model):
    class StatusChoices(models.TextChoices):
        ORCAMENTO = "orcamento", "Orçamento"
        COTACAO = "cotacao", "Cotação"
        AGUARDANDO_PAGAMENTO = "aguardando_pagamento", "Aguardando pagamento"
        PAGAMENTO_PROCESSANDO = "pagamento_processando", "Pagamento processando"
        PAGO = "pago", "Pago"
        CANCELADO = "cancelado", "Cancelado"
        ODOO = "odoo", "Odoo"  # status específico para vendas importadas do Odoo

    class StatusPagamentoChoices(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        PROCESSANDO = "processando", "Processando"
        APROVADO = "aprovado", "Aprovado"
        RECUSADO = "recusado", "Recusado"
        CANCELADO = "cancelado", "Cancelado"
        ODOO = "odoo", "Odoo"  # status específico para vendas importadas do Odoo

    registro_origem = models.ForeignKey(
        Registro,
        on_delete=models.PROTECT,
        related_name="vendas",
        null=True,
        blank=True,
    )

    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.PROTECT,
        related_name="vendas",
        null=True,
        blank=True,
    )

    vendedor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vendas"
    )

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    nome_cliente = models.CharField(max_length=255)
    tipo_documento = models.CharField(max_length=5)
    documento = models.CharField(max_length=32, db_index=True)
    localizacao = models.CharField(max_length=255, blank=True, default="")
    forma_pagamento = models.CharField(max_length=20)

    profissao_cliente = models.CharField(max_length=255, blank=True, default="")
    telefone = models.CharField(max_length=50, blank=True, default="")
    endereco = models.TextField(blank=True, default="")

    valor_entrada = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    quantidade_parcelas = models.PositiveIntegerField(default=1)
    valor_desconto = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    valor_frete = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    observacoes = models.TextField(blank=True, null=True)

    equipamentos_json = models.JSONField(blank=True, null=True, default=list)

    # status geral da venda
    status = models.CharField(
        max_length=30,
        choices=StatusChoices.choices,
        default=StatusChoices.ORCAMENTO,
        db_index=True,
    )

    token_pagamento = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        unique=True
    )

    status_pagamento = models.CharField(
        max_length=20,
        choices=StatusPagamentoChoices.choices,
        default=StatusPagamentoChoices.PENDENTE,
        db_index=True,
    )

    link_pagamento = models.URLField(
        blank=True,
        null=True
    )

    codigo_pix = models.TextField(blank=True, default="")
    codigo_pix_imagem = models.TextField(blank=True, default="")
    pix_tid = models.CharField(max_length=64, blank=True, default="")
    pix_expira_em = models.DateTimeField(null=True, blank=True)

    link_pagamento_atualizado_em = models.DateTimeField(null=True, blank=True)

    # retorno Rede
    rede_reference = models.CharField(max_length=120, blank=True, default="")
    rede_tid = models.CharField(max_length=64, blank=True, default="")
    rede_nsu = models.CharField(max_length=64, blank=True, default="")
    rede_authorization_code = models.CharField(max_length=64, blank=True, default="")

    # Odoo
    odoo_partner_id = models.IntegerField(null=True, blank=True)
    odoo_user_id = models.IntegerField(null=True, blank=True)
    odoo_vendedor_id = models.IntegerField(null=True, blank=True)
    odoo_sale_order_id = models.IntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        ordering = ["-criado_em"]

    def __str__(self):
        return f"Venda #{self.id} - {self.nome_cliente}"

    @staticmethod
    def _only_digits(value: str) -> str:
        return "".join(ch for ch in (value or "") if ch.isdigit())

    def _tipo_normalizado(self) -> str:
        return (self.tipo_documento or "").strip().upper()

    def pode_receber_pagamento(self) -> bool:
        return self.status in {
            self.StatusChoices.COTACAO,
            self.StatusChoices.AGUARDANDO_PAGAMENTO,
        } and self.status_pagamento in {
            self.StatusPagamentoChoices.PENDENTE,
            self.StatusPagamentoChoices.RECUSADO,
        }

    def marcar_aguardando_pagamento(self):
        self.status = self.StatusChoices.AGUARDANDO_PAGAMENTO
        self.status_pagamento = self.StatusPagamentoChoices.PENDENTE

    def marcar_pagamento_processando(self):
        self.status = self.StatusChoices.PAGAMENTO_PROCESSANDO
        self.status_pagamento = self.StatusPagamentoChoices.PROCESSANDO

    def marcar_pago(self):
        self.status = self.StatusChoices.PAGO
        self.status_pagamento = self.StatusPagamentoChoices.APROVADO
        self.token_pagamento = None
        self.link_pagamento = None

    def marcar_pagamento_recusado(self):
        self.status = self.StatusChoices.AGUARDANDO_PAGAMENTO
        self.status_pagamento = self.StatusPagamentoChoices.RECUSADO

    def marcar_status_odoo(self):
        self.status = self.StatusChoices.ODOO
        self.status_pagamento = self.StatusPagamentoChoices.ODOO
        self.token_pagamento = None
        self.link_pagamento = None

    def limpar_dados_pix(self):
        self.codigo_pix = ""
        self.codigo_pix_imagem = ""
        self.pix_tid = ""
        self.pix_expira_em = None
        self.rede_reference = ""
        self.rede_tid = ""
        self.rede_nsu = ""
        self.rede_authorization_code = ""

    def atualizar_link_pagamento(self, link: str | None):
        self.link_pagamento = link
        self.link_pagamento_atualizado_em = models.functions.Now()

    def marcar_pago(self):
        self.status = self.StatusChoices.PAGO
        self.status_pagamento = self.StatusPagamentoChoices.APROVADO
        self.token_pagamento = None
        self.link_pagamento = None

    def _sync_cliente_from_venda(self):
        from clientes.models import Cliente

        tipo = self._tipo_normalizado()
        doc = self._only_digits(self.documento)
        self.documento = doc

        if self.registro_origem_id and getattr(self.registro_origem, "cliente_id", None):
            self.cliente = self.registro_origem.cliente

        if not self.cliente_id and tipo and doc:
            if tipo == "CPF" and len(doc) == 11:
                self.cliente, _ = Cliente.objects.get_or_create(
                    cpf=doc,
                    defaults={
                        "nome": (self.nome_cliente or "").strip(),
                        "localizacao": (self.localizacao or "").strip(),
                        "cnpj": None,
                    },
                )
            elif tipo == "CNPJ" and len(doc) == 14:
                self.cliente, _ = Cliente.objects.get_or_create(
                    cnpj=doc,
                    defaults={
                        "nome": (self.nome_cliente or "").strip(),
                        "localizacao": (self.localizacao or "").strip(),
                        "cpf": None,
                    },
                )

        if self.cliente_id:
            cliente = self.cliente
            changed = False

            if tipo == "CPF" and len(doc) == 11:
                exists_other = Cliente.objects.filter(cpf=doc).exclude(pk=cliente.pk).exists()
                if exists_other:
                    raise ValidationError({"documento": "Este CPF já está cadastrado em outro cliente."})

                if (cliente.cpf or "") != doc:
                    cliente.cpf = doc
                    changed = True

            elif tipo == "CNPJ" and len(doc) == 14:
                exists_other = Cliente.objects.filter(cnpj=doc).exclude(pk=cliente.pk).exists()
                if exists_other:
                    raise ValidationError({"documento": "Este CNPJ já está cadastrado em outro cliente."})

                if (cliente.cnpj or "") != doc:
                    cliente.cnpj = doc
                    changed = True

            new_nome = (self.nome_cliente or "").strip()
            if new_nome and (cliente.nome or "") != new_nome:
                cliente.nome = new_nome
                changed = True

            new_tel = (self.telefone or "").strip()
            if new_tel and (cliente.telefone or "") != new_tel:
                cliente.telefone = new_tel
                changed = True

            new_end = (self.endereco or "").strip()
            if new_end and (cliente.endereco or "") != new_end:
                cliente.endereco = new_end
                changed = True

            if changed:
                cliente.save()

    def save(self, *args, **kwargs):
        self._sync_cliente_from_venda()
        super().save(*args, **kwargs)


class VendaItem(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="itens")
    descricao = models.CharField(max_length=255)
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        verbose_name = "Item da venda"
        verbose_name_plural = "Itens da venda"
        ordering = ["id"]

    def __str__(self):
        return f"{self.descricao} ({self.quantidade})"


class VendaArquivo(models.Model):
    venda = models.ForeignKey(Venda, on_delete=models.CASCADE, related_name="arquivos")
    arquivo = models.FileField(upload_to=upload_venda_path)
    nome = models.CharField(max_length=255, blank=True, default="")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Arquivo da venda"
        verbose_name_plural = "Arquivos da venda"
        ordering = ["-criado_em"]

    def __str__(self):
        return self.nome or os.path.basename(self.arquivo.name)