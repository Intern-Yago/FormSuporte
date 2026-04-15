from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Registro

from django.contrib.auth import get_user_model
from django.db.models import Q

class EquipamentoContainsFilter(admin.SimpleListFilter):
    title = "Equipamento (contém)"
    parameter_name = "equip"

    def lookups(self, request, model_admin):
        return ()

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            return queryset.filter(equipamentos_resumo__icontains=value.strip())
        return queryset


@admin.register(Registro)
class RegistroAdmin(admin.ModelAdmin):
    list_display = (
        "criado_em",
        "nome_vendedor_link",   # ✅ sempre mostra nome; vira link se houver user
        "nome_cliente_link",    # ✅ sempre mostra nome; vira link se houver cliente
        "equipamentos_resumo",
    )

    list_filter = (
        "nome_vendedor",
        "nome_cliente",
        "forma_pagamento",
        "tipo_documento",
        ("criado_em", admin.DateFieldListFilter),
        EquipamentoContainsFilter,
    )

    search_fields = (
        "nome_vendedor",
        "nome_cliente",
        "documento",
        "equipamentos_resumo",
        "cliente__nome",
        "cliente__cpf",
        "cliente__cnpj",
        # só funciona se você tiver vendedor_user no model:
        "vendedor_user__username",
        "vendedor_user__email",
        "vendedor_user__first_name",
        "vendedor_user__last_name",
    )

    ordering = ("-criado_em",)
    date_hierarchy = "criado_em"
    list_per_page = 50
    readonly_fields = ("criado_em", "nome_vendedor_link", "nome_cliente_link")

    fieldsets = (
        ("Identificação", {
            "fields": (
                "criado_em",
                "nome_vendedor",
                "nome_vendedor_link",
                "nome_cliente",
                "nome_cliente_link",
                "cliente",
                "localizacao",
            )
        }),
        ("Documento", {
            "fields": ("tipo_documento", "documento")
        }),
        ("Equipamentos", {
            "fields": ("equipamentos_resumo", "equipamentos_json")
        }),
        ("Pagamento", {
            "fields": ("forma_pagamento", "quantidade_parcelas", "valor_entrada", "valor_desconto", "valor_frete", "valor_avista")
        }),
        ("Observações", {
            "fields": ("observacoes",)
        }),
    )

    @admin.display(description="Vendedor", ordering="nome_vendedor")
    def nome_vendedor_link(self, obj):
        """
        Sempre mostra o nome_vendedor.
        Se conseguir achar um usuário pelo nome_vendedor, transforma em link
        para o admin do usuário (o admin do app 'usuarios', se for onde o User está registrado).
        """
        nome = (obj.nome_vendedor or "").strip() or "—"

        # cache simples por request (evita muitas queries na listagem)
        request = getattr(self, "_current_request", None)
        cache = getattr(self, "_vendedor_user_cache", None)
        if cache is None:
            self._vendedor_user_cache = {}
            cache = self._vendedor_user_cache

        key = nome.casefold()
        if key in cache:
            user = cache[key]
        else:
            user = self._find_user_by_vendedor_nome(nome)
            cache[key] = user

        if not user:
            return nome

        try:
            url = reverse(
                f"admin:{user._meta.app_label}_{user._meta.model_name}_change",
                args=[user.pk],
            )
            return format_html('<a href="{}">{}</a>', url, nome)
        except Exception:
            return nome


    def _find_user_by_vendedor_nome(self, nome: str):
        """
        Heurística best-effort:
        - tenta username/email exato
        - tenta nome completo (first_name last_name)
        - tenta contains (cuidado: só linka se der match único)
        """
        User = get_user_model()
        s = (nome or "").strip()
        if not s:
            return None

        # 1) username/email exato
        qs = User.objects.filter(
            Q(username__iexact=s) | Q(email__iexact=s)
        )
        if qs.count() == 1:
            return qs.first()

        # 2) nome completo exato (first_name + last_name)
        # (isso funciona bem quando você salva "João Silva" no nome_vendedor)
        parts = s.split()
        if len(parts) >= 2:
            first = parts[0]
            last = " ".join(parts[1:])
            qs = User.objects.filter(first_name__iexact=first, last_name__iexact=last)
            if qs.count() == 1:
                return qs.first()

        # 3) fallback: contains em first_name/last_name/username (só se for único)
        qs = User.objects.filter(
            Q(first_name__icontains=s) |
            Q(last_name__icontains=s) |
            Q(username__icontains=s)
        )
        if qs.count() == 1:
            return qs.first()

        return None

    @admin.display(description="Cliente", ordering="nome_cliente")
    def nome_cliente_link(self, obj: Registro):
        """
        Sempre mostra nome_cliente.
        Se existir FK cliente, vira link pro admin do cliente.
        """
        nome = (obj.nome_cliente or "").strip() or "—"

        if not obj.cliente_id:
            return nome

        try:
            url = reverse("admin:clientes_cliente_change", args=[obj.cliente_id])
            return format_html('<a href="{}">{}</a>', url, nome)
        except Exception:
            return nome
        
        