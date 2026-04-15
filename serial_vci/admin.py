from django.contrib import admin
from .models import SerialVCI, SerialFoto

class FotosInline(admin.TabularInline):
    model = SerialFoto
    extra = 1

@admin.register(SerialVCI)
class SerialVCIAdmin(admin.ModelAdmin):
    list_display = ("id", "numero_vci", "cliente", "email", "pedido")
    search_fields = ("id", "numero_vci", "cliente", "email")
    list_filter = ("cliente", "email")
    ordering = ("-id",)
    inlines = [FotosInline]


@admin.register(SerialFoto)
class SerialFotoAdmin(admin.ModelAdmin):
    list_display = ("id", "serial", "imagem")
    search_fields = ("id", "serial__numero_vci")
