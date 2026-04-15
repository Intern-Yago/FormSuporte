from django import forms
from .models import Veiculo, METHOD_CHOICES

# forms.py - Definições de Formulários Django para o App 'form'

def get_flat_choices():
    """
    Função auxiliar para 'achatar' as escolhas agrupadas (METHOD_CHOICES)
    em uma lista simples de tuplas (valor, rótulo) para uso em campos de formulário.
    
    Esta função é necessária para campos MultipleChoiceField que usam CheckboxSelectMultiple.
    """
    flat_choices = []
    # Itera sobre os valores (grupos de escolhas) do dicionário METHOD_CHOICES
    for grupo in METHOD_CHOICES.values():
        # Adiciona todas as escolhas do grupo à lista
        flat_choices.extend(grupo.items())
    return flat_choices

class VeiculoForm(forms.ModelForm):
    """
    Formulário baseado no modelo Veiculo.
    
    Personaliza a exibição de campos específicos, como os campos de método
    (add_key, read_password, etc.) para usar múltiplos checkboxes.
    """
    
    # Define os campos de método como MultipleChoiceField com CheckboxSelectMultiple
    # Isso permite que o usuário selecione múltiplos métodos para cada operação.
    
    # Campo para métodos de 'Adicionar Chave'
    add_key = forms.MultipleChoiceField(
        choices=get_flat_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'method-checkbox'}),
        label='Adicionar Chave (OBD)' # Define o rótulo aqui para maior clareza
    )

    # Campo para métodos de 'Ler Senha'
    read_password = forms.MultipleChoiceField(
        choices=get_flat_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'method-checkbox'}),
        label='Ler Senha (Bench)'
    )

    # Campo para métodos de 'Aprendizado Remoto'
    remote_learning = forms.MultipleChoiceField(
        choices=get_flat_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'method-checkbox'}),
        label='Aprendizado Remoto'
    )
    
    # Campo para métodos de 'All Keys Lost'
    keys_lost = forms.MultipleChoiceField(
        choices=get_flat_choices(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'method-checkbox'}),
        label='All Keys Lost'
    )

    class Meta:
        """Configurações do Meta do formulário."""
        model = Veiculo
        # Inclui todos os campos do modelo
        fields = '__all__'
        
        # Define widgets personalizados para campos específicos
        widgets = {
            'frequencia': forms.Select(attrs={'class': 'form-select frequency-select'}),
            'tipo_chave': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: ID46, Crypto'}),
            'transponder': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: T5, Megamos'}),
            'immo_part_replacement': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: NEC, EEPROM'})
        }
        
        # Os rótulos (labels) para os campos de método foram movidos para a definição do campo
        # acima para maior coesão e para evitar duplicação/confusão.
        # Os rótulos de outros campos serão gerados automaticamente pelo Django.
        # labels = {
        #     'add_key': 'Adicionar Chave (OBD)',
        #     'read_password': 'Ler Senha (Bench)',
        #     'remote_learning': 'Aprendizado Remoto',
        #     'keys_lost': 'All Keys Lost'
        # }

