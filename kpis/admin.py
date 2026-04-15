from django.contrib import admin
from .models import KpiRegistroMensal


@admin.register(KpiRegistroMensal)
class KpiRegistroMensalAdmin(admin.ModelAdmin):
    list_display = (
        "get_tecnico",
        "get_area",
        "ano",
        "mes",
        "total_atendimentos",
        "nota_media",
        "updated_at",
    )
    list_filter = (
        "ano", 
        "mes", 
        "perfil__area", 
        "perfil__user__is_active",
        "perfil__setor"
    )
    search_fields = (
        "perfil__user__first_name", 
        "perfil__user__last_name", 
        "perfil__user__username", 
        "perfil__user__email"
    )
    autocomplete_fields = ("perfil",)
    list_per_page = 100

    @admin.display(description="Técnico", ordering="perfil__user__first_name")
    def get_tecnico(self, obj):
        return obj.perfil.user.get_full_name() or obj.perfil.user.username

    @admin.display(description="Área/Categoria", ordering="perfil__area")
    def get_area(self, obj):
        return obj.perfil.area or "-"