from django.forms import modelform_factory, inlineformset_factory
from .models import Pedido, PedidoItem
from django import forms

class PedidoForm(forms.ModelForm):
    data = forms.DateField(
        widget=forms.DateInput(
            attrs={"type": "date"}
        )
    )

    class Meta:
        model = Pedido
        fields = [
            "data",
            "cliente",
            "cep",
            "cidade",
            "bairro",
            "rua",
            "numero",
            "complemento",
            "cnpj_cpf",
            "ie",
            "email",
            "transporte",
            "vendedor",
            "observacoes",
        ]



PedidoItemFormSet = inlineformset_factory(
    Pedido,
    PedidoItem,
    fields=[
        "referencia", "quantidade", "unidade",
        "descricao", "preco_unitario"
    ],
    extra=1,
    can_delete=True
)
