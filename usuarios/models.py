from django.db import models
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()

class UsuarioProfile(models.Model):
    class Role(models.TextChoices):
        DONO = "dono", "Dono"
        DIRETOR = "diretor", "Diretor"
        GESTOR = "gestor", "Gestor"
        COLABORADOR = "colaborador", "Colaborador"

    class Setor(models.TextChoices):
        MARKETING = "marketing", "Marketing"
        FINANCEIRO = "financeiro", "Financeiro"
        SUPORTE = "suporte", "Suporte"
        TI = "ti", "TI"
        COMERCIAL = "comercial", "Comercial"

    class GrupoComercial(models.TextChoices):
        INTERNO = "interno", "Interno"
        EXTERNO = "externo", "Externo"
        PARCEIRO = "parceiro", "Parceiro"
        REVENDEDOR = "revendedor", "Revendedor"
        SMURFS = "smurfs", "Smurfs"

    # Mantemos isso apenas como auxiliares de texto, sem forçar no CharField
    class AreaSuporte(models.TextChoices):
        CHAVEIRO = "chaveiro", "Chaveiro"
        DIAGNOSTICO = "diagnostico", "Diagnóstico"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    # Integração Odoo
    odoo_user_id = models.IntegerField(
        verbose_name="ID do Vendedor no Odoo",
        null=True,
        blank=True,
        help_text="O ID deste vendedor na tabela res.users do Odoo."
    )

    role = models.CharField(max_length=20, choices=Role.choices, blank=True, null=True)
    setor = models.CharField(max_length=20, choices=Setor.choices, blank=True, null=True)
    grupo_comercial = models.CharField(max_length=20, choices=GrupoComercial.choices, blank=True, null=True)

    # O campo volta a ficar livre (sem choices)
    area = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Área/filtro de responsabilidade do usuário dentro do painel."
    )
    
    cpf_cnpj = models.CharField(max_length=30, blank=True, null=True)
    contato = models.CharField(max_length=100, blank=True, null=True)
    allowed_systems = models.JSONField(default=None, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil de Usuário"
        verbose_name_plural = "Perfis de Usuários"

    def clean(self):
        super().clean()

        # Regra 1: grupo_comercial só pode existir para colaborador/comercial
        if self.grupo_comercial and not (self.role == self.Role.COLABORADOR and self.setor == self.Setor.COMERCIAL):
            raise ValidationError({
                "grupo_comercial": "O grupo comercial só pode ser definido para colaborador do setor comercial."
            })

        if not (self.role == self.Role.COLABORADOR and self.setor == self.Setor.COMERCIAL):
            self.grupo_comercial = None

        # Regra 2: Se for do setor SUPORTE, a área TEM que ser chaveiro ou diagnóstico
        if self.setor == self.Setor.SUPORTE and self.area:
            areas_validas = [self.AreaSuporte.CHAVEIRO, self.AreaSuporte.DIAGNOSTICO]
            if self.area not in areas_validas:
                raise ValidationError({
                    "area": f"Para usuários do setor Suporte, a área deve ser uma destas: {', '.join(areas_validas)}."
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        role_display = self.get_role_display() if self.role else "Sem papel"
        return f"{self.user.username} ({role_display})"


class KpiRegistroMensal(models.Model):
    perfil = models.ForeignKey(
        UsuarioProfile, 
        on_delete=models.CASCADE, 
        related_name="kpis_mensais",
        null=True,   # <-- Adicionado para não travar a migração
        blank=True   # <-- Adicionado para não travar a migração
    )
    ano = models.IntegerField()
    mes = models.IntegerField()
    total_atendimentos = models.IntegerField(default=0)
    nota_media = models.DecimalField(max_digits=4, decimal_places=2, default=0)
    
    class Meta:
        unique_together = ('perfil', 'ano', 'mes')