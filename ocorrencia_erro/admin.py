# ocorrencia_erro/admin.py
from django.contrib import admin

from .models import (
    Record,
    CountryPermission,
    Country,
    Device,
    OptionItem,
    RecordStatusLog,
)

# =========================
# Movimentação (timeline)
# =========================
class RecordMovementInline(admin.TabularInline):
    model = RecordStatusLog
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "user", "event_type", "from_status", "to_status", "field", "note")
    fields = ("created_at", "user", "event_type", "from_status", "to_status", "field", "note")
    ordering = ("-created_at", "-id")
    show_change_link = False


# =========================
# Admins
# =========================
@admin.register(Record)
class RecordAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "data", "responsible", "device", "country")
    search_fields = ("id", "codigo_externo", "responsible", "device__name", "country__name", "serial")
    list_filter = ("status", "responsible", "country")
    inlines = [RecordMovementInline]


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)  # necessário pro autocomplete_fields funcionar


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(OptionItem)
class OptionItemAdmin(admin.ModelAdmin):
    list_display = ("category", "area", "label", "parent", "order", "active", "cod_usuario", "created_at")
    list_filter = ("category", "area", "active")
    search_fields = ("label", "parent__label")
    list_editable = ("order", "active")


@admin.register(CountryPermission)
class CountryPermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "country")
    search_fields = ("user__username", "user__first_name", "user__last_name", "country__name")
    list_filter = ("country",)
    autocomplete_fields = ("user", "country")