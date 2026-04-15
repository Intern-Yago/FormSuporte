# usuarios/admin.py
# ============================================================
# App principal de gestão de utilizadores no painel Django.
# Centraliza: permissões por país (CountryPermission) +
#             histórico de ações do admin (LogEntry).
# ============================================================

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from ocorrencia_erro.models import CountryPermission
from .models import UsuarioProfile

User = get_user_model()


# =============================================================
# 1) Trick para Autocomplete do Perfil funcionar em outros Apps
# =============================================================
@admin.register(UsuarioProfile)
class UsuarioProfileAdmin(admin.ModelAdmin):
    """
    Este ModelAdmin existe apenas para viabilizar o uso do 
    'autocomplete_fields = ("perfil",)' no KpiRegistroMensalAdmin.
    Ocultamos ele da index do Django Admin para manter a tela limpa.
    """
    search_fields = ("user__username", "user__first_name", "user__last_name", "user__email")
    
    def get_model_perms(self, request):
        # Retorna um dicionário vazio para esconder este menu da listagem do admin
        return {}


# =============================================================
# 2) Inline: Países de responsabilidade (via CountryPermission)
# =============================================================

class CountryPermissionInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            country = form.cleaned_data.get("country")
            if not country:
                continue

            if country.pk in seen:
                raise ValidationError(
                    "Você adicionou o mesmo país mais de uma vez para este utilizador."
                )
            seen.add(country.pk)


class CountryPermissionInline(admin.TabularInline):
    model = CountryPermission
    formset = CountryPermissionInlineFormSet
    extra = 0
    autocomplete_fields = ("country",)
    verbose_name = "País de responsabilidade"
    verbose_name_plural = "Países de responsabilidade"


# =============================================================
# 3) Inline: Histórico de ações do Admin (LogEntry)
# =============================================================

class LogEntryInline(admin.TabularInline):
    model = LogEntry
    fk_name = "user"
    extra = 0
    can_delete = False
    verbose_name_plural = "Histórico de ações (Admin Log)"
    ordering = ("-action_time",)

    LIMIT = 10
    fields = ("quando", "tipo_conteudo", "objeto", "acao", "msg_curta")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("content_type", "user").order_by("-action_time")

    def get_formset(self, request, obj=None, **kwargs):
        FormSet = super().get_formset(request, obj, **kwargs)
        limit = self.LIMIT

        class LimitedFormSet(FormSet):
            def __init__(self, *args, **inner_kwargs):
                super().__init__(*args, **inner_kwargs)
                self.queryset = self.queryset.order_by("-action_time")[:limit]

        return LimitedFormSet

    @admin.display(description="Quando")
    def quando(self, obj):
        return timezone.localtime(obj.action_time).strftime("%d/%m/%Y %H:%M")

    @admin.display(description="Tipo de conteúdo")
    def tipo_conteudo(self, obj):
        if not obj.content_type_id:
            return "-"
        return f"{obj.content_type.app_label} | {obj.content_type.name}"

    @admin.display(description="Objeto")
    def objeto(self, obj):
        if not obj.content_type_id or not obj.object_id:
            return obj.object_repr
        try:
            url = reverse(
                f"admin:{obj.content_type.app_label}_{obj.content_type.model}_change",
                args=[obj.object_id],
            )
            return format_html('<a href="{}">{}</a>', url, obj.object_repr)
        except Exception:
            return obj.object_repr

    @admin.display(description="Flag de ação")
    def acao(self, obj):
        return {1: "Criar", 2: "Modificar", 3: "Excluir"}.get(
            obj.action_flag, str(obj.action_flag)
        )

    @admin.display(description="Mensagem")
    def msg_curta(self, obj):
        msg = (obj.change_message or "").replace("\n", " ").strip()
        return (msg[:120] + "…") if len(msg) > 120 else (msg or "-")


# =============================================================
# 4) CustomUserAdmin — fonte única de configuração do User
# =============================================================

class UsuarioProfileInline(admin.StackedInline):
    model = UsuarioProfile
    can_delete = False
    fk_name = "user"
    verbose_name_plural = "Perfil unificado do usuário"

    fields = (
        "odoo_user_id",
        "role",
        "setor",
        "grupo_comercial",
        "area",
        "cpf_cnpj",
        "contato",
        "allowed_systems",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

class CustomUserAdmin(BaseUserAdmin):
    inlines = [UsuarioProfileInline, CountryPermissionInline, LogEntryInline]

    readonly_fields = ("countries_responsible_display", "ver_mais_logs") + tuple(
        getattr(BaseUserAdmin, "readonly_fields", ())
    )

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Informações pessoais", {"fields": ("first_name", "last_name", "email")}),
        (
            "Permissões",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Datas importantes", {"fields": ("last_login", "date_joined")}),
        ("Logs", {"fields": ("ver_mais_logs",)}),
    )

    # ----------------------------------------------------------
    # Colunas e filtros extras da listagem
    # ----------------------------------------------------------
    @admin.display(description="Setor", ordering="profile__setor")
    def get_setor(self, obj):
        return obj.profile.get_setor_display() if hasattr(obj, 'profile') and obj.profile.setor else "-"

    @admin.display(description="Cargo", ordering="profile__role")
    def get_cargo(self, obj):
        return obj.profile.get_role_display() if hasattr(obj, 'profile') and obj.profile.role else "-"

    @admin.display(description="Países Responsáveis")
    def countries_responsible(self, obj):
        qs = obj.country_permissions.select_related("country").all()
        return ", ".join([p.country.name for p in qs]) or "-"

    @admin.display(description="Países Responsáveis")
    def countries_responsible_display(self, obj):
        return self.countries_responsible(obj)

    # Adiciona as colunas novas na visualização da tabela
    list_display = BaseUserAdmin.list_display + ("get_setor", "get_cargo", "countries_responsible")

    # Adiciona os filtros na barra lateral
    list_filter = BaseUserAdmin.list_filter + ("profile__setor", "profile__role", "profile__area")

    # ----------------------------------------------------------
    # Link para o histórico completo de logs
    # ----------------------------------------------------------
    @admin.display(description="Histórico completo")
    def ver_mais_logs(self, obj):
        if not obj or not obj.pk:
            return "-"
        total = LogEntry.objects.filter(user=obj).count()
        url = (
            reverse("admin:admin_logentry_changelist")
            + f"?user__id__exact={obj.pk}"
        )
        return format_html(
            '<a class="button" href="{}">Ver mais logs (total: {})</a>',
            url,
            total,
        )


# =============================================================
# Registro — desregistra qualquer UserAdmin anterior e registra
# o CustomUserAdmin como único responsável.
# =============================================================
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, CustomUserAdmin)