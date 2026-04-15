# clientes/models.py
from django.db import models
from django.core.exceptions import ValidationError


class ShopifySyncConfig(models.Model):
    last_cursor = models.CharField(max_length=255, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração Shopify Sync"

    def __str__(self):
        return f"Último Cursor: {self.last_cursor or 'Início'}"


class Cliente(models.Model):
    nome = models.CharField(max_length=255)
    razao_social = models.CharField("Razão Social", max_length=255, blank=True, default="")
    profissao = models.CharField(max_length=255, blank=True, default="")

    cpf = models.CharField(max_length=11, null=True, blank=True, unique=True, db_index=True)
    cnpj = models.CharField(max_length=14, null=True, blank=True, unique=True, db_index=True)

    odoo_partner_id = models.BigIntegerField("ID no Odoo", null=True, blank=True, db_index=True)
    shopify_customer_id = models.CharField("ID no Shopify", max_length=255, null=True, blank=True, db_index=True)
    
    
    inscricao_estadual = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    telefone = models.CharField(max_length=32, blank=True, default="")
    observacoes = models.TextField(blank=True, default="")

    # ✅ Endereço principal do cliente (cadastro / faturamento)
    endereco = models.CharField("Endereço", max_length=255, blank=True, default="")
    numero = models.CharField("Número", max_length=30, blank=True, default="")
    complemento = models.CharField("Complemento", max_length=80, blank=True, default="")
    bairro = models.CharField("Bairro", max_length=120, blank=True, default="")
    cidade = models.CharField("Cidade", max_length=120, blank=True, default="")
    uf = models.CharField("UF", max_length=2, blank=True, default="")
    cep = models.CharField("CEP", max_length=9, blank=True, default="")

    # ⚠️ Campo antigo (era "Localização") — manter só para regra de cálculo/preço
    localizacao = models.CharField("UF (cálculo do simulador)", max_length=255, blank=True, default="")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def clean(self):
        super().clean()

        if self.cpf == "":
            self.cpf = None
        if self.cnpj == "":
            self.cnpj = None

        if self.cpf:
            if (not self.cpf.isdigit()) or len(self.cpf) != 11:
                raise ValidationError({"cpf": "CPF deve conter 11 dígitos numéricos."})

        if self.cnpj:
            if (not self.cnpj.isdigit()) or len(self.cnpj) != 14:
                raise ValidationError({"cnpj": "CNPJ deve conter 14 dígitos numéricos."})

        # normaliza UF
        if self.uf:
            self.uf = self.uf.strip().upper()[:2]
        if self.localizacao:
            self.localizacao = self.localizacao.strip().upper()

        # normaliza CEP
        if self.cep:
            digits = "".join(ch for ch in self.cep if ch.isdigit())
            if len(digits) == 8:
                self.cep = f"{digits[:5]}-{digits[5:]}"
            else:
                self.cep = self.cep.strip()

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        parts = [self.nome]
        if self.cnpj:
            parts.append(f"CNPJ:{self.cnpj}")
        if self.cpf:
            parts.append(f"CPF:{self.cpf}")
        return " - ".join(parts)

    @property
    def endereco_formatado(self):
        parts = []
        if self.endereco:
            parts.append(self.endereco)
        if self.numero:
            parts.append(self.numero)
        if self.bairro:
            parts.append(self.bairro)
        if self.cidade:
            parts.append(self.cidade)
        if self.uf:
            parts.append(self.uf)
        if self.cep:
            parts.append(self.cep)
        return " - ".join([p for p in parts if p])


class ClienteEndereco(models.Model):
    """
    Endereços adicionais do cliente.
    - Você vai usar esse model para entregar.
    - O Cliente continua com endereço principal (cadastro/faturamento).
    """
    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.CASCADE,
        related_name="enderecos",
        db_index=True,
    )
    odoo_endereco_partner_id = models.BigIntegerField(
        "ID do endereço no Odoo (res.partner filho)",
        null=True,
        blank=True,
        db_index=True,
    )
    nome = models.CharField("Nome do endereço", max_length=80)  # ex: "Casa", "Oficina", "Filial SP"
    is_ativo = models.BooleanField(default=True)

    # opcional: marcar um padrão de entrega (se quiser)
    is_padrao_entrega = models.BooleanField(default=False)

    endereco = models.CharField("Endereço", max_length=255, blank=True, default="")
    numero = models.CharField("Número", max_length=30, blank=True, default="")
    complemento = models.CharField("Complemento", max_length=80, blank=True, default="")
    bairro = models.CharField("Bairro", max_length=120, blank=True, default="")
    cidade = models.CharField("Cidade", max_length=120, blank=True, default="")
    uf = models.CharField("UF", max_length=2, blank=True, default="")
    cep = models.CharField("CEP", max_length=9, blank=True, default="")

    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Endereço do cliente"
        verbose_name_plural = "Endereços do cliente"
        indexes = [
            models.Index(fields=["cliente", "is_ativo"]),
        ]
        constraints = [
            # garante só 1 padrão de entrega ativo por cliente
            models.UniqueConstraint(
                fields=["cliente"],
                condition=models.Q(is_padrao_entrega=True),
                name="uniq_cliente_endereco_padrao_entrega",
            )
        ]

    def clean(self):
        super().clean()

        # normaliza UF
        if self.uf:
            self.uf = self.uf.strip().upper()[:2]

        # normaliza CEP
        if self.cep:
            digits = "".join(ch for ch in self.cep if ch.isdigit())
            if len(digits) == 8:
                self.cep = f"{digits[:5]}-{digits[5:]}"
            else:
                self.cep = self.cep.strip()

        if not self.nome or not self.nome.strip():
            raise ValidationError({"nome": "Você precisa nomear o endereço (ex: Casa, Oficina, Filial)."})

    def save(self, *args, **kwargs):
        self.full_clean()

        # se marcou como padrão, desmarca os outros (pra não depender só do constraint)
        if self.is_padrao_entrega:
            ClienteEndereco.objects.filter(cliente=self.cliente, is_padrao_entrega=True).exclude(pk=self.pk).update(
                is_padrao_entrega=False
            )

        super().save(*args, **kwargs)

    @property
    def endereco_formatado(self):
        parts = []
        if self.endereco:
            parts.append(self.endereco)
        if self.numero:
            parts.append(self.numero)
        if self.bairro:
            parts.append(self.bairro)
        if self.cidade:
            parts.append(self.cidade)
        if self.uf:
            parts.append(self.uf)
        if self.cep:
            parts.append(self.cep)
        return " - ".join([p for p in parts if p])

    def __str__(self):
        return f"{self.cliente_id} - {self.nome}"