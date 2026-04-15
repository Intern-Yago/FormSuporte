# serializers.py - Definições de Serializers para o App 'API'

from rest_framework import serializers
from .models import Equipamentos, TipoEquipamento, MarcaEquipamento
from clientes.models import Cliente as ClienteUnificado
from situacao_veiculo.models import Cliente as ClienteSuporte

class TipoEquipamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoEquipamento
        fields = '__all__'

class MarcaEquipamentoSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarcaEquipamento
        fields = '__all__'

class EquipamentosSerializer(serializers.ModelSerializer):
    tipo = TipoEquipamentoSerializer(read_only=True)

    class Meta:
        model = Equipamentos
        fields = '__all__'

class ClienteUnificadoSerializer(serializers.ModelSerializer):
    """Serializer para o modelo completo de clientes (app clientes)"""
    nomeCliente = serializers.CharField(source='nome', read_only=True, default="")
    documento = serializers.SerializerMethodField()

    class Meta:
        model = ClienteUnificado
        fields = [
            'id', 'nome', 'nomeCliente', 'cpf', 'cnpj', 
            'documento', 'email', 'cidade', 'uf',
        ]

    def get_documento(self, obj):
        try:
            return obj.cnpj or obj.cpf or ""
        except:
            return ""

class ClienteSuporteSerializer(serializers.ModelSerializer):
    """Serializer para o modelo de suporte (app situacao_veiculo)"""
    nomeCliente = serializers.CharField(source='nome', read_only=True)
    documento = serializers.CharField(source='cnpj', read_only=True)
    telefone = serializers.CharField(source='tel', read_only=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = ClienteSuporte
        fields = [
            'id', 'serial', 'serial_sec', 'nome', 'nomeCliente', 
            'cnpj', 'documento', 'tel', 'telefone', 'equipamento', 
            'vencimento', 'status',
        ]
