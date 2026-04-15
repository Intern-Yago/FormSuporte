from django.contrib import admin
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from .models import Cliente, ClienteEndereco


class ClienteEnderecoInline(admin.StackedInline):
    model = ClienteEndereco
    extra = 0
    min_num = 0
    fields = (
        "nome",
        "is_ativo",
        "is_padrao_entrega",
        "odoo_endereco_partner_id",
        "endereco",
        "numero",
        "complemento",
        "bairro",
        "cidade",
        "uf",
        "cep",
    )
    classes = ("collapse",)


class DocumentoFilter(admin.SimpleListFilter):
    title = "Documento"
    parameter_name = "documento_tipo"

    def lookups(self, request, model_admin):
        return (
            ("cpf", "Apenas CPF"),
            ("cnpj", "Apenas CNPJ"),
            ("ambos", "CPF e CNPJ"),
            ("sem", "Sem documento"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "cpf":
            return queryset.exclude(cpf__isnull=True).exclude(cpf="")
        if value == "cnpj":
            return queryset.exclude(cnpj__isnull=True).exclude(cnpj="")
        if value == "ambos":
            return queryset.exclude(cpf__isnull=True).exclude(cpf="").exclude(cnpj__isnull=True).exclude(cnpj="")
        if value == "sem":
            return queryset.filter(cpf__isnull=True, cnpj__isnull=True)
        return queryset


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nome",
        "documento_principal",
        "telefone",
        "email",
        "cidade",
        "uf",
        "odoo_partner_id",
        "enderecos_extras_count",
        "criado_em",
    )
    search_fields = (
        "id",
        "nome",
        "cpf",
        "cnpj",
        "telefone",
        "email",
        "cidade",
        "uf",
        "odoo_partner_id",
    )
    list_filter = (
        DocumentoFilter,
        "uf",
        "criado_em",
        "atualizado_em",
    )
    readonly_fields = (
        "criado_em",
        "atualizado_em",
        "preview_endereco_principal",
    )
    fields = (
        ("nome", "profissao"),
        ("cpf", "cnpj"),
        ("email", "telefone"),
        ("odoo_partner_id", "localizacao"),
        ("inscricao_estadual",),
        ("endereco", "numero"),
        ("complemento", "bairro"),
        ("cidade", "uf", "cep"),
        ("preview_endereco_principal",),
        ("observacoes",),
        ("criado_em", "atualizado_em"),
    )
    inlines = [ClienteEnderecoInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_enderecos_count=Count("enderecos", distinct=True))

    @admin.display(description="Documento")
    def documento_principal(self, obj):
        return obj.cnpj or obj.cpf or "-"

    @admin.display(description="Endereços extras")
    def enderecos_extras_count(self, obj):
        return getattr(obj, "_enderecos_count", 0)

    @admin.display(description="Endereço principal")
    def preview_endereco_principal(self, obj):
        return obj.endereco_formatado or "-"


@admin.register(ClienteEndereco)
class ClienteEnderecoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "nome",
        "cidade",
        "uf",
        "is_padrao_entrega",
        "is_ativo",
        "odoo_endereco_partner_id",
    )
    search_fields = (
        "cliente__nome",
        "cliente__cpf",
        "cliente__cnpj",
        "nome",
        "cidade",
        "uf",
        "cep",
        "odoo_endereco_partner_id",
    )
    list_filter = (
        "is_ativo",
        "is_padrao_entrega",
        "uf",
    )