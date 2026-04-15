from openpyxl import Workbook

from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.contrib.admin.views.main import ChangeList
from django.db import models
from django.db.models import Count, Q
from django.forms import Textarea
from django.http import HttpResponse
from django.urls import path, reverse
from django.utils import formats, timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html

from .models import Cliente, SerialSearchLog


class SerialDuplicadoFilter(admin.SimpleListFilter):
    title = "Serial duplicado"
    parameter_name = "serial_duplicado"

    def lookups(self, request, model_admin):
        return (("sim", "Duplicados"), ("nao", "Não duplicados"))

    def queryset(self, request, queryset):
        duplicados = (
            Cliente.objects.values("serial")
            .annotate(serial_count=Count("id"))
            .filter(serial_count__gt=1)
            .values("serial")
        )
        if self.value() == "sim":
            return queryset.filter(serial__in=duplicados)
        elif self.value() == "nao":
            return queryset.exclude(serial__in=duplicados)
        return queryset


class OrigemCriacaoFilter(admin.SimpleListFilter):
    title = "Origem da criação"
    parameter_name = "origem_criacao"

    def lookups(self, request, model_admin):
        return (
            ("usuario", "Criado por usuário"),
            ("sistema", "Criado pelo sistema"),
        )

    def queryset(self, request, queryset):
        if self.value() == "usuario":
            return queryset.filter(created_by__isnull=False)
        elif self.value() == "sistema":
            return queryset.filter(created_by__isnull=True)
        return queryset


class ClienteChangeList(ChangeList):
    CUSTOM_FILTER_KEYS = {
        "ativacao_de",
        "ativacao_ate",
        "vencimento_de",
        "vencimento_ate",
    }

    def get_filters_params(self, params=None):
        params = super().get_filters_params(params)
        for key in self.CUSTOM_FILTER_KEYS:
            params.pop(key, None)
        return params


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    change_list_template = "admin/situacao_veiculo/cliente/change_list.html"

    list_display = (
        "serial",
        "serial_sec",
        "nome",
        "equipamento",
        "data",
        "vencimento",
        "anos_para_vencimento",
        "contactado",
        "origem_criacao",
        "criado_por_display",
        "atualizado_mes",
        "acoes",
    )
    search_fields = (
        "serial",
        "serial_sec",
        "nome",
        "equipamento",
        "status_message_custom",
        "mensagem",
        "created_by__username",
        "updated_by__username",
    )
    list_filter = (
        SerialDuplicadoFilter,
        "contactado",
        OrigemCriacaoFilter,
        "created_by",
    )
    list_editable = ("anos_para_vencimento",)

    fieldsets = (
        (None, {"fields": ("nome", "data", "anos_para_vencimento", "vencimento")}),
        ("Detalhes", {"fields": ("serial", "serial_sec", "cnpj", "tel", "equipamento")}),
        ("Controle", {"fields": ("contactado",)}),
        ("Histórico de buscas (por serial)", {"fields": ("historico_buscas", "ver_mais_buscas")}),
        (
            "Mensagens (opcional)",
            {
                "classes": ("collapse",),
                "fields": ("status_message_custom", "mensagem"),
                "description": "Se vazio, usa a mensagem padrão calculada pelo status.",
            },
        ),
        ("Auditoria", {"fields": ("created_by", "updated_at", "updated_by")}),
    )

    readonly_fields = (
        "created_by",
        "updated_at",
        "updated_by",
        "historico_buscas",
        "ver_mais_buscas",
    )

    formfield_overrides = {
        models.TextField: {"widget": Textarea(attrs={"rows": 5, "style": "width: 100%"})},
    }

    def get_changelist(self, request, **kwargs):
        return ClienteChangeList

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "exportar-xlsx/",
                self.admin_site.admin_view(self.exportar_xlsx_view),
                name="situacao_veiculo_cliente_exportar_xlsx",
            ),
        ]
        return custom_urls + urls

    def _apply_custom_date_filters(self, queryset, request):
        ativacao_de = parse_date(request.GET.get("ativacao_de", "") or "")
        ativacao_ate = parse_date(request.GET.get("ativacao_ate", "") or "")
        vencimento_de = parse_date(request.GET.get("vencimento_de", "") or "")
        vencimento_ate = parse_date(request.GET.get("vencimento_ate", "") or "")

        if ativacao_de and ativacao_ate:
            if ativacao_ate < ativacao_de:
                ativacao_de, ativacao_ate = ativacao_ate, ativacao_de
            queryset = queryset.filter(data__range=(ativacao_de, ativacao_ate))
        elif ativacao_de:
            queryset = queryset.filter(data=ativacao_de)

        if vencimento_de and vencimento_ate:
            if vencimento_ate < vencimento_de:
                vencimento_de, vencimento_ate = vencimento_ate, vencimento_de
            queryset = queryset.filter(vencimento__range=(vencimento_de, vencimento_ate))
        elif vencimento_de:
            queryset = queryset.filter(vencimento=vencimento_de)

        return queryset

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return self._apply_custom_date_filters(queryset, request)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context.update(
            {
                "ativacao_de": request.GET.get("ativacao_de", ""),
                "ativacao_ate": request.GET.get("ativacao_ate", ""),
                "vencimento_de": request.GET.get("vencimento_de", ""),
                "vencimento_ate": request.GET.get("vencimento_ate", ""),
                "export_xlsx_url": reverse("admin:situacao_veiculo_cliente_exportar_xlsx"),
            }
        )
        return super().changelist_view(request, extra_context=extra_context)

    def exportar_xlsx_view(self, request):
        changelist = self.get_changelist_instance(request)
        queryset = changelist.get_queryset(request)
        queryset = self._apply_custom_date_filters(queryset, request)

        wb = Workbook()
        ws = wb.active
        ws.title = "Situação Suporte"

        ws.append(
            [
                "Serial",
                "Serial Sec",
                "Nome",
                "Equipamento",
                "Data",
                "Vencimento",
                "Anos para vencimento",
                "Contactado",
                "Origem",
                "Criado por",
                "Atualizado em",
            ]
        )

        for obj in queryset:
            criado_por = "-"
            if obj.created_by:
                criado_por = obj.created_by.get_full_name() or obj.created_by.username

            origem = "Usuário" if obj.created_by_id else "Sistema"
            atualizado_em = (
                timezone.localtime(obj.updated_at).strftime("%d/%m/%Y %H:%M")
                if obj.updated_at
                else ""
            )

            ws.append(
                [
                    obj.serial or "",
                    obj.serial_sec or "",
                    obj.nome or "",
                    obj.equipamento or "",
                    obj.data.strftime("%d/%m/%Y") if obj.data else "",
                    obj.vencimento.strftime("%d/%m/%Y") if obj.vencimento else "",
                    obj.anos_para_vencimento if obj.anos_para_vencimento is not None else "",
                    "Sim" if obj.contactado else "Não",
                    origem,
                    criado_por,
                    atualizado_em,
                ]
            )

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="situacao_suporte_filtrado.xlsx"'
        wb.save(response)
        return response

    def acoes(self, obj):
        url = reverse("admin:situacao_veiculo_cliente_delete", args=[obj.pk])
        return format_html('<a class="button" href="{}">Excluir</a>', url)

    acoes.short_description = "Excluir"

    @admin.display(description="Origem")
    def origem_criacao(self, obj):
        return "Usuário" if obj.created_by_id else "Sistema"

    @admin.display(ordering="created_by__username", description="Criado por")
    def criado_por_display(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return format_html("<span style='color:#6b7280;'>Sistema</span>")

    @admin.display(description="Atualização (mês)")
    def atualizado_mes(self, obj):
        if not obj.updated_at:
            return "-"
        return formats.date_format(timezone.localtime(obj.updated_at), "F Y")

    def _logs_for_cliente(self, obj):
        s1 = (obj.serial or "").strip()
        s2 = (obj.serial_sec or "").strip()
        q = Q()
        if s1:
            q |= Q(searched_serial__iexact=s1) | Q(resolved_serial__iexact=s1)
        if s2:
            q |= Q(searched_serial__iexact=s2) | Q(resolved_serial__iexact=s2)
        if not q:
            return SerialSearchLog.objects.none()
        return SerialSearchLog.objects.select_related("user").filter(q).order_by("-created_at")

    @admin.display(description="Histórico de buscas")
    def historico_buscas(self, obj):
        logs = list(self._logs_for_cliente(obj)[:20])
        if not logs:
            return format_html("<em>Sem buscas registradas para este serial.</em>")

        rows = []
        for l in logs:
            dt = timezone.localtime(l.created_at).strftime("%d/%m/%Y %H:%M")
            user = getattr(l.user, "username", "-")
            rows.append(
                f"<tr>"
                f"<td style='padding:6px 10px; white-space:nowrap;'>{dt}</td>"
                f"<td style='padding:6px 10px;'>{user}</td>"
                f"<td style='padding:6px 10px; font-family:monospace;'>{l.searched_serial}</td>"
                f"<td style='padding:6px 10px; font-family:monospace;'>{l.resolved_serial or '-'}</td>"
                f"</tr>"
            )

        html = (
            "<div style='max-width:100%; overflow:auto; border:1px solid #e5e7eb; border-radius:10px;'>"
            "<table style='border-collapse:collapse; width:100%; min-width:650px;'>"
            "<thead>"
            "<tr style='background:#f8fafc;'>"
            "<th style='text-align:left; padding:8px 10px;'>Quando</th>"
            "<th style='text-align:left; padding:8px 10px;'>Usuário</th>"
            "<th style='text-align:left; padding:8px 10px;'>Serial digitado</th>"
            "<th style='text-align:left; padding:8px 10px;'>Serial resolvido</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
            + "".join(rows)
            + "</tbody></table></div>"
        )
        return format_html(html)

    @admin.display(description="Ver mais buscas")
    def ver_mais_buscas(self, obj):
        logs_qs = self._logs_for_cliente(obj)
        total = logs_qs.count()
        if total == 0:
            return "-"
        s1 = (obj.serial or "").strip()
        s2 = (obj.serial_sec or "").strip()
        search_q = " ".join([x for x in [s1, s2] if x])
        url = reverse("admin:situacao_veiculo_serialsearchlog_changelist")
        return format_html(
            '<a class="button" href="{}?q={}">Ver mais (total: {})</a>',
            url,
            search_q,
            total,
        )


@admin.register(SerialSearchLog)
class SerialSearchLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "searched_serial", "resolved_serial")
    list_filter = ("created_at", "user")
    search_fields = ("searched_serial", "resolved_serial", "user__username")
    ordering = ("-created_at",)
    list_per_page = 50


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    date_hierarchy = "action_time"
    list_display = ("action_time", "user", "content_type", "object_repr", "action_flag", "change_message")
    list_filter = ("action_flag", "content_type", "user")
    search_fields = ("object_repr", "change_message", "user__username")
    ordering = ("-action_time",)
    list_per_page = 50