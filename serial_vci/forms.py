from django import forms
from .models import SerialVCI

class SerialVCIForm(forms.ModelForm):
    # Formulário de Adição
    class Meta:
        model = SerialVCI
        fields = [
            "numero_vci",
            "numero_tablet",
            "numero_prog",
            "cliente",
            "email",
            "telefone",
            "pedido",
        ]

class SerialVCIEditForm(forms.ModelForm):
    # NOVO FORMULÁRIO: Apenas campos permitidos para edição
    class Meta:
        model = SerialVCI
        fields = [
            "numero_vci",
            "numero_tablet",
            "numero_prog",
            "email", 
            "telefone"
        ]