from django.contrib import admin
from django import forms
from .models import Equipamentos, MarcaEquipamento, TipoEquipamento


class EquipamentoForm(forms.ModelForm):
    class Meta:
        model = Equipamentos
        fields = "__all__"
        widgets = {
            "detalhes": forms.Textarea(attrs={
                "style": "height: 220px; width: 95%;",
                "placeholder": "Use *negrito*, _itálico_, ~tachado~, `código` e links https://"
            }),
            "detalhes_sp": forms.Textarea(attrs={
                "style": "height: 220px; width: 95%;",
                "placeholder": "Versão alternativa (SP)."
            }),
        }

    def clean(self):
        cleaned = super().clean()

        boleto = cleaned.get("boleto")
        parcelas = float(cleaned.get("parcelas") or 0)

        # Se boleto NÃO é aceito, parcelas no boleto não fazem sentido (aviso simples)
        # (não bloqueio, só organizo o dado)
        if boleto is False and parcelas > 0:
            self.add_error(
                "parcelas",
                "Você desmarcou 'Aceita pagamento via boleto'. "
                "Então 'Parcelas sugeridas no boleto' normalmente deve ficar vazio."
            )

        return cleaned


@admin.register(Equipamentos)
class EquipamentoAdmin(admin.ModelAdmin):
    form = EquipamentoForm

    list_display = ("nome", "marca", "grupo", "disponibilidade", "avista", "boleto")
    list_filter = ("grupo", "marca", "disponibilidade", "avista", "boleto")
    search_fields = ("nome", "marca__nome", "grupo__nome")

    readonly_fields = ("detalhes_html", "detalhes_sp_html")

    fieldsets = (
        ("Básico", {
            "fields": ("nome", "marca", "grupo", "disponibilidade"),
        }),

        ("Pagamento e Parcelas (REGRA REAL)", {
            "fields": ("avista", "boleto"),
            "description": (
                "<b>Como funciona:</b><br>"
                "• <b>Somente 1x (à vista)</b>: limita o cliente a escolher apenas 1 parcela.<br>"
                "• <b>Aceita pagamento via boleto</b>: permite pagar com boleto (1x ou parcelado).<br>"
                "• Mesmo com <b>Somente 1x</b>, pode pagar 1x no cartão e 1x no boleto (se boleto estiver habilitado)."
            ),
        }),

        ("Configurações do simulador (automação)", {
            "fields": (
                "parcelas",
                "entrada_sp_cnpj",
                "entrada_outros_cnpj",
                "entrada_outros_cpf",
            ),
            "description": (
                "Esses campos alimentam a automação e o simulador.<br>"
            ),
        }),

        ("Preços", {
            "fields": ("custo", "custo_geral", "custo_cnpj", "custo_cpf"),
        }),

        ("Texto (geral)", {
            "fields": ("detalhes", "detalhes_html"),
        }),

        ("Texto (SP)", {
            "fields": ("detalhes_sp", "detalhes_sp_html"),
        }),
    )


@admin.register(MarcaEquipamento)
class MarcaEquipamentoAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)


@admin.register(TipoEquipamento)
class TipoEquipamentoAdmin(admin.ModelAdmin):
    list_display = ("nome",)
    search_fields = ("nome",)
