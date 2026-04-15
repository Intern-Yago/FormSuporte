from decimal import Decimal
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from usuarios.models import UsuarioProfile

class KpiRegistroMensal(models.Model):
    # Substituímos tecnico por perfil
    perfil = models.ForeignKey(
        UsuarioProfile,
        on_delete=models.CASCADE,
        related_name="registros_mensais_kpi",
        null=True,   # <-- Coloque AQUI!
        blank=True   # <-- Coloque AQUI!
    )
    ano = models.PositiveIntegerField()
    mes = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    total_atendimentos = models.PositiveIntegerField(default=0)
    nota_media = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(10)],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Registro Mensal KPI"
        verbose_name_plural = "Registros Mensais KPI"
        # Ajustamos a ordenação para buscar o nome do usuário atrelado ao perfil
        ordering = ("-ano", "-mes", "-total_atendimentos", "perfil__user__first_name")
        constraints = [
            models.UniqueConstraint(
                fields=("perfil", "ano", "mes"), # Atualizado aqui também
                name="unique_kpi_perfil_ano_mes",
            )
        ]

    def __str__(self):
        nome = self.perfil.user.get_full_name() or self.perfil.user.username
        return f"{nome} - {self.mes:02d}/{self.ano}"