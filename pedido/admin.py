from django.contrib import admin
from .models import Venda, VendaItem, VendaArquivo


class VendaItemInline(admin.TabularInline):
    model = VendaItem
    extra = 0


class VendaArquivoInline(admin.TabularInline):
    model = VendaArquivo
    extra = 0


@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "nome_cliente",
        "documento",
        "forma_pagamento",
        "status",
        "status_pagamento",
        "valor_total_admin",
        "odoo_sale_order_id",
        "rede_tid",
        "criado_em",
    )
    list_filter = (
        "status",
        "status_pagamento",
        "forma_pagamento",
        "tipo_documento",
        "criado_em",
    )
    search_fields = (
        "id",
        "nome_cliente",
        "documento",
        "rede_tid",
        "rede_nsu",
        "rede_reference",
    )
    readonly_fields = (
        "criado_em",
        "atualizado_em",
        "rede_tid",
        "rede_nsu",
        "rede_authorization_code",
    )
    inlines = [VendaItemInline, VendaArquivoInline]

    fieldsets = (
        ("Geral", {
            "fields": (
                "registro_origem",
                "cliente",
                "vendedor",
                "nome_cliente",
                "tipo_documento",
                "documento",
                "forma_pagamento",
                "status",
                "status_pagamento",
            )
        }),
        ("Financeiro", {
            "fields": (
                "valor_entrada",
                "quantidade_parcelas",
                "valor_desconto",
                "valor_frete",
            )
        }),
        ("Pagamento", {
            "fields": (
                "token_pagamento",
                "link_pagamento",
                "rede_reference",
                "rede_tid",
                "rede_nsu",
                "rede_authorization_code",
            )
        }),
        ("Odoo", {
            "fields": (
                "odoo_partner_id",
                "odoo_user_id",
                "odoo_vendedor_id",
                "odoo_sale_order_id",
            )
        }),
        ("Outros", {
            "fields": (
                "localizacao",
                "profissao_cliente",
                "telefone",
                "endereco",
                "observacoes",
                "equipamentos_json",
                "criado_em",
                "atualizado_em",
            )
        }),
    )

    def valor_total_admin(self, obj):
        total = 0
        for item in (obj.equipamentos_json or []):
            try:
                total += float(item.get("valor_total", 0) or 0)
            except Exception:
                pass
        return f"R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    valor_total_admin.short_description = "Valor total"


@admin.register(VendaItem)
class VendaItemAdmin(admin.ModelAdmin):
    list_display = ("id", "venda", "descricao", "quantidade", "valor_unitario")
    search_fields = ("descricao", "venda__nome_cliente", "venda__documento")


@admin.register(VendaArquivo)
class VendaArquivoAdmin(admin.ModelAdmin):
    list_display = ("id", "venda", "nome", "criado_em")
    search_fields = ("nome", "venda__nome_cliente", "venda__documento")