from django.db import models
from multiselectfield import MultiSelectField

# models.py - Definições de Modelos Django para o App 'form'

# Constante global para as opções de método (OBD ou BENCH)
# Usada para campos MultiSelectField que representam métodos de programação.
METHOD_CHOICES = {
    "OBD": {
        'allOBD': 'allOBD', # Exemplo: Programação completa via OBD
        'partOBD': 'partOBD' # Exemplo: Programação parcial via OBD
    },
    "BENCH": {
        'allBENCH': 'allBENCH', # Exemplo: Programação completa via Bench
        'partBENCH': 'partBENCH' # Exemplo: Programação parcial via Bench
    },
}

def get_flat_choices():
    """
    Função auxiliar para 'achatar' METHOD_CHOICES em uma lista simples de tuplas (valor, rótulo).
    
    Necessário para campos MultiSelectField e para o formulário (forms.py).
    """
    flat_choices = []
    # Itera sobre os valores (grupos de escolhas) do dicionário METHOD_CHOICES
    for grupo in METHOD_CHOICES.values():
        # Adiciona todas as escolhas do grupo à lista
        flat_choices.extend(grupo.items())
    return flat_choices

class Veiculo(models.Model):
    """
    Modelo para armazenar informações detalhadas sobre um veículo e seus
    métodos de programação de chaves.
    """
    
    # Opções de escolha para o campo 'frequencia'
    FREQUENCIA_CHOICES = [
        ('315', '315 MHz'),
        ('433', '433 MHz'),
    ]

    # --- Campos de Identificação Básica ---
    pais = models.CharField(max_length=100, verbose_name='País')
    brand = models.CharField(max_length=100, verbose_name='Marca')
    modelo = models.CharField(max_length=100, verbose_name='Modelo')
    ano = models.CharField(max_length=20, verbose_name='Ano')

    # --- Campos de Detalhes Técnicos ---
    sistema = models.CharField(
        max_length=100, 
        null=True, 
        blank=True, 
        verbose_name='Sistema'
    )
    tipo_chave = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name='Tipo de Chave'
    )
    transponder = models.CharField(
        max_length=100, 
        blank=True, 
        verbose_name='Transponder'
    )
    immo_part_replacement = models.CharField(
        max_length=1000, 
        blank=True, 
        verbose_name='Substituição da Peça IMMO'
    )

    # --- Campo com Choices Simples ---
    frequencia = models.CharField(
        max_length=3,
        # Adiciona uma opção vazia para permitir que o campo não seja selecionado
        choices=[('', '---------')] + FREQUENCIA_CHOICES,
        blank=True,
        verbose_name='Frequência'
    )

    # --- Campos de Métodos de Programação (MultiSelectField) ---
    # Estes campos usam MultiSelectField para permitir a seleção de múltiplos métodos (OBD/BENCH)
    
    add_key = MultiSelectField(
        choices=get_flat_choices(),
        blank=True,
        verbose_name='Add Key'
    )
    read_password = MultiSelectField(
        choices=get_flat_choices(),
        blank=True,
        verbose_name='Read Password'
    )
    remote_learning = MultiSelectField(
        choices=get_flat_choices(),
        blank=True,
        verbose_name='Remote Learning'
    )
    # Renomeado de 'key_lost' para 'keys_lost' para consistência com forms.py
    key_lost = MultiSelectField(
        choices=get_flat_choices(),
        blank=True,
        verbose_name='Keys Lost'
    )

    class Meta:
        """Configurações adicionais do modelo."""
        verbose_name = "Veículo"
        verbose_name_plural = "Veículos"

    def __str__(self):
        """Retorna uma representação em string do objeto (Marca Modelo (Ano))."""
        return f"{self.brand} {self.modelo} ({self.ano})"
