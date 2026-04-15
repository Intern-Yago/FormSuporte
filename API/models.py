from django.db import models
import re
from django.utils.html import format_html, escape


class TipoEquipamento(models.Model):
    nome = models.CharField(
        "Tipo do equipamento",
        max_length=100,
        help_text="Ex: Diagnóstico, Imobilizador, Programador, etc."
    )

    class Meta:
        verbose_name = "Tipo de equipamento"
        verbose_name_plural = "Tipos de equipamento"

    def __str__(self):
        return self.nome


class MarcaEquipamento(models.Model):
    nome = models.CharField("Marca", max_length=30)

    class Meta:
        verbose_name = "Marca"
        verbose_name_plural = "Marcas"

    def __str__(self):
        return self.nome


class Equipamentos(models.Model):
    """
    SEMÂNTICA FINAL:

    - boleto = aceita pagamento via boleto (1x ou parcelado).
      Se boleto=False, NÃO pode pagar com boleto de forma alguma.

    - avista = limita parcelas para no máximo 1 (ou seja: "somente 1x").
      Mesmo com avista=True, ainda pode pagar 1x no cartão e 1x no boleto (se boleto=True).

    - parcelas e valor_cartao_12x são usados para automação:
      Se não existir nenhum indicativo de parcelamento (boleto >1 ou cartão 12x >0),
      avista vira True (somente 1x).
    """

    # ---------- Identificação ----------
    nome = models.CharField("Nome do equipamento", max_length=100, unique=True)

    marca = models.ForeignKey(
        MarcaEquipamento,
        on_delete=models.CASCADE,
        related_name="equipamentos",
        verbose_name="Marca",
    )

    grupo = models.ForeignKey(
        TipoEquipamento,
        on_delete=models.CASCADE,
        related_name="equipamentos",
        verbose_name="Tipo",
    )

    # ---------- Preços ----------
    custo = models.FloatField(
        "Custo interno",
        blank=True,
        null=True,
        help_text="Opcional (controle interno)."
    )

    custo_geral = models.FloatField("Preço SP (padrão)")
    custo_cnpj = models.FloatField("Preço fora de SP (CNPJ)", null=True, blank=True)
    custo_cpf = models.FloatField("Preço fora de SP (CPF)", null=True, blank=True)

    # ---------- Condições padrão ----------
    entrada_sp_cnpj = models.FloatField("Entrada SP (CNPJ)", blank=True, null=True)
    entrada_outros_cnpj = models.FloatField("Entrada fora de SP (CNPJ)", blank=True, null=True)
    entrada_outros_cpf = models.FloatField("Entrada fora de SP (CPF)", blank=True, null=True)

    parcelas = models.FloatField(
        "Parcelas sugeridas no boleto",
        blank=True,
        null=True,
        help_text="Usado na automação. Ex: 12 para 12x no boleto."
    )

    valor_cartao_12x = models.FloatField(
        "Valor da parcela no cartão (12x) (automação)",
        blank=True,
        null=True,
        help_text="Usado na automação. Se > 0, indica que existe parcelamento no cartão."
    )

    # ---------- Disponibilidade ----------
    disponibilidade = models.BooleanField("Ativo", default=True, blank=True)

    # ---------- Pagamento / Parcelamento ----------
    avista = models.BooleanField(
        "Somente 1x (à vista)",
        default=False,
        help_text=(
            "Se marcado, o cliente só pode escolher 1 parcela. "
            "Ainda pode pagar 1x no cartão e 1x no boleto (se boleto estiver habilitado)."
        )
    )

    boleto = models.BooleanField(
        "Aceita pagamento via boleto",
        default=True,
        help_text="Se desmarcado, não pode pagar com boleto (nem 1x, nem parcelado)."
    )

    # ---------- Textos ----------
    detalhes = models.TextField(
        "Texto (geral / WhatsApp)",
        blank=True,
        null=True,
        help_text="Use *negrito*, _itálico_, ~tachado~, `código` e links https://"
    )

    detalhes_html = models.TextField(
        "Preview (HTML gerado)",
        editable=False,
        blank=True,
        null=True
    )

    detalhes_sp = models.TextField("Texto SP (WhatsApp)", blank=True, null=True)

    detalhes_sp_html = models.TextField(
        "Preview SP (HTML gerado)",
        editable=False,
        blank=True,
        null=True
    )

    class Meta:
        verbose_name = "Equipamento"
        verbose_name_plural = "Equipamentos"

    def __str__(self):
        return f"{self.nome} - {self.marca} - {self.grupo}"

    def save(self, *args, **kwargs):
        # -----------------------------
        # 1) Detecta override manual
        # -----------------------------
        manual_override = False
        if self.pk:
            old = Equipamentos.objects.filter(pk=self.pk).values("avista", "boleto").first()
            if old and ((self.avista != old["avista"]) or (self.boleto != old["boleto"])):
                manual_override = True

        # -----------------------------
        # 2) Automação (se NÃO for manual)
        #    IMPORTANTÍSSIMO:
        #    - Aqui só automatizamos o avista (limite 1x)
        #    - boleto é método de pagamento, não "parcelamento"
        # -----------------------------
        if not manual_override:
            parcelas_boleto = float(self.parcelas or 0)
            valor_cartao_12x = float(self.valor_cartao_12x or 0)

            # Se não há indicativo de parcelamento em nenhum meio -> somente 1x
            self.avista = (parcelas_boleto < 2 and valor_cartao_12x <= 0)

        # -----------------------------
        # 3) HTML
        # -----------------------------
        self.detalhes_html = self._convert_whatsapp_to_html(self.detalhes) if self.detalhes else None
        self.detalhes_sp_html = self._convert_whatsapp_to_html(self.detalhes_sp) if self.detalhes_sp else None

        super().save(*args, **kwargs)

    def formatted_detalhes(self):
        return format_html(self.detalhes_html) if self.detalhes_html else ""
    formatted_detalhes.short_description = "Preview"

    def formatted_detalhes_sp(self):
        return format_html(self.detalhes_sp_html) if self.detalhes_sp_html else ""
    formatted_detalhes_sp.short_description = "Preview SP"

    @staticmethod
    def _convert_whatsapp_to_html(text: str) -> str:
        if not text:
            return ""

        text = escape(text)

        text = re.sub(
            r"(https?://\S+)",
            r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
            text
        )

        text = re.sub(r"\*(.*?)\*", r"<strong>\1</strong>", text)
        text = re.sub(r"_(.*?)_", r"<em>\1</em>", text)
        text = re.sub(r"~(.*?)~", r"<strike>\1</strike>", text)
        text = re.sub(r"`(.*?)`", r"<code>\1</code>", text)

        text = re.sub(r"^- (.*)$", r"<li>\1</li>", text, flags=re.MULTILINE)

        if "<li>" in text:
            text = text.replace("<li>", "<ul><li>", 1) + "</ul>"

        text = text.replace("\n", "<br>")
        return text
