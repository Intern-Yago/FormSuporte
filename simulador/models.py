from django.db import models


class Registro(models.Model):
    TIPO_DOCUMENTO_CHOICES = [
        ("CPF", "CPF"),
        ("CNPJ", "CNPJ"),
    ]

    FORMA_PAGAMENTO_CHOICES = [
        ("Cartao", "Cartão"),
        ("Boleto", "Boleto"),
        ("Pix", "Pix"),
    ]

    # vínculo com Cliente central (não pode derrubar o Registro)
    cliente = models.ForeignKey(
        "clientes.Cliente",
        on_delete=models.PROTECT,
        related_name="registros_orcamento",
        null=True,
        blank=True,
    )

    nome_vendedor = models.CharField("Nome do vendedor", max_length=255, default="")
    nome_cliente = models.CharField("Nome do cliente", max_length=255)

    tipo_documento = models.CharField("Tipo de documento", max_length=5, choices=TIPO_DOCUMENTO_CHOICES)
    documento = models.CharField("CPF/CNPJ", max_length=32, db_index=True)
    localizacao = models.CharField("Localização", max_length=255, blank=True, default="")

    forma_pagamento = models.CharField("Forma de pagamento", max_length=10, choices=FORMA_PAGAMENTO_CHOICES)

    # equipamentos
    equipamentos_resumo = models.TextField("Equipamentos (resumo)", blank=True, default="")
    equipamentos_json = models.JSONField("Equipamentos (JSON)", blank=True, null=True)

    valor_entrada = models.DecimalField("Valor de entrada", max_digits=10, decimal_places=2, default=0)
    quantidade_parcelas = models.PositiveIntegerField("Quantidade de parcelas", default=1)
    valor_desconto = models.DecimalField("Valor de desconto", max_digits=10, decimal_places=2, default=0)
    valor_frete = models.DecimalField("Valor do frete", max_digits=10, decimal_places=2, default=0)

    valor_avista = models.DecimalField(
        "Valor à vista (sem taxa)",
        max_digits=12,
        decimal_places=2,
        default=0,
        blank=True,
        null=True,
    )

    observacoes = models.TextField("Observações", blank=True, null=True)

    criado_em = models.DateTimeField("Data de geração", auto_now_add=True)

    @property
    def valor_total_equipamentos(self):
        try:
            return sum(float(item.get("valor_total", 0)) for item in (self.equipamentos_json or []))
        except:
            return 0

    @property
    def valor_total_final(self):
        return self.valor_total_equipamentos - float(self.valor_desconto) + float(self.valor_frete)

    @property
    def valor_parcela(self):
        if self.quantidade_parcelas > 0:
            saldo = max(0, self.valor_total_final - float(self.valor_entrada))
            return saldo / self.quantidade_parcelas
        return 0

    class Meta:
        verbose_name = "Registro"
        verbose_name_plural = "Registros"
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["tipo_documento", "documento"]),
            models.Index(fields=["cliente", "criado_em"]),
        ]

    def __str__(self):
        return f"{self.nome_cliente} - {self.documento} ({self.criado_em:%d/%m/%Y})"

    @staticmethod
    def _only_digits(value: str) -> str:
        return "".join(ch for ch in (value or "") if ch.isdigit())

    def _sync_cliente_best_effort(self):
        """
        Tenta criar/achar Cliente central e linkar.
        Nunca deve derrubar a criação do Registro.
        """
        from clientes.models import Cliente

        doc = self._only_digits(self.documento)
        self.documento = doc

        if not self.tipo_documento or not doc:
            return None

        if self.tipo_documento == "CPF" and len(doc) != 11:
            return None
        if self.tipo_documento == "CNPJ" and len(doc) != 14:
            return None

        if self.tipo_documento == "CPF":
            cliente, _ = Cliente.objects.get_or_create(
                cpf=doc,
                defaults={
                    "nome": self.nome_cliente or "",
                    "localizacao": self.localizacao or "",
                    "cnpj": None,
                },
            )
        else:
            cliente, _ = Cliente.objects.get_or_create(
                cnpj=doc,
                defaults={
                    "nome": self.nome_cliente or "",
                    "localizacao": self.localizacao or "",
                    "cpf": None,
                },
            )

        changed = False
        if (not cliente.nome) and self.nome_cliente:
            cliente.nome = self.nome_cliente
            changed = True
        if (not cliente.localizacao) and self.localizacao:
            cliente.localizacao = self.localizacao
            changed = True
        if changed:
            cliente.save(update_fields=["nome", "localizacao", "atualizado_em"])

        return cliente

    def save(self, *args, **kwargs):
        """
        Registro sempre salva.
        Cliente é best effort: tenta linkar depois, sem travar.
        """
        self.documento = self._only_digits(self.documento)

        super().save(*args, **kwargs)

        if self.cliente_id:
            return

        try:
            cliente = self._sync_cliente_best_effort()
            if cliente and not self.cliente_id:
                self.cliente = cliente
                super().save(update_fields=["cliente", "documento"])
        except Exception as e:
            print(f"[Registro #{self.pk}] Falha ao criar/linkar Cliente: {e}")