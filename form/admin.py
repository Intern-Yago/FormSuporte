from django.contrib import admin
from django.utils.html import format_html
from .models import Veiculo

class VeiculoAdmin(admin.ModelAdmin):
    # Configuração da lista de exibição
    list_display = (
        'brand_upper',
        'modelo_upper',
        'ano',
        'pais_upper',
        'frequencia',
        'sistema_upper'
    )
    
    list_display_links = ('brand_upper', 'modelo_upper')
    list_filter = ('pais', 'brand', 'ano', 'frequencia')
    search_fields = ('brand', 'modelo', 'ano', 'pais')
    list_per_page = 25
    ordering = ('brand', 'modelo', 'ano')
    
    # Campos para edição rápida
    list_editable = ('ano', 'frequencia')
    
    # Agrupamento de campos no formulário
    fieldsets = (
        ('Informações Básicas', {
            'fields': ('pais', 'brand', 'modelo', 'ano')
        }),
        ('Detalhes Técnicos', {
            'fields': ('sistema', 'tipo_chave', 'transponder', 'frequencia'),
        }),
        ('Métodos de Programação', {
            'fields': ('add_key', 'read_password', 'remote_learning', 'key_lost'),
            'description': 'Selecione os métodos disponíveis para este veículo'
        }),
        ('IMMO', {
            'fields': ('immo_part_replacement',),
            'classes': ('wide',)
        }),
    )
    
    # Métodos customizados para exibição
    def brand_upper(self, obj):
        return obj.brand.upper() if obj.brand else '-'
    brand_upper.short_description = 'MARCA'
    brand_upper.admin_order_field = 'brand'
    
    def modelo_upper(self, obj):
        return obj.modelo.upper() if obj.modelo else '-'
    modelo_upper.short_description = 'MODELO'
    modelo_upper.admin_order_field = 'modelo'
    
    def pais_upper(self, obj):
        return obj.pais.upper() if obj.pais else '-'
    pais_upper.short_description = 'PAÍS'
    pais_upper.admin_order_field = 'pais'
    
    def sistema_upper(self, obj):
        return obj.sistema.upper() if obj.sistema else '-'
    sistema_upper.short_description = 'SISTEMA'
    
    def frequencia_display(self, obj):
        return dict(Veiculo.FREQUENCIA_CHOICES).get(obj.frequencia, '-')
    frequencia_display.short_description = 'FREQUÊNCIA'
    
    
    # Filtros hierárquicos
    class Media:
        css = {
            'all': ('css/admin_veiculos.css',)
        }
        js = ('js/admin_veiculos.js',)

admin.site.register(Veiculo, VeiculoAdmin)