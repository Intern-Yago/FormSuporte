# ocorrencia/services/dashboard.py
from django.db.models import Count, Q
from ocorrencia_erro.models import Record, CountryPermission
from datetime import timedelta
from django.utils import timezone

def aplicar_filtro_data(qs, request):
    data_inicio = request.GET.get("data_inicio")
    data_fim = request.GET.get("data_fim")
    periodo = (request.GET.get("periodo") or "").strip().lower()

    hoje = timezone.now().date()

    if periodo == "semanal":
        return qs.filter(data__gte=hoje - timedelta(days=7))

    if periodo == "mensal":
        return qs.filter(data__gte=hoje.replace(day=1))

    if periodo == "anual":
        return qs.filter(data__year=hoje.year)

    if data_inicio:
        qs = qs.filter(data__gte=data_inicio)

    if data_fim:
        qs = qs.filter(data__lte=data_fim)

    return qs


from ocorrencia_erro.utils.permissions import check_user_full_permission

def base_queryset_por_usuario(user):
    qs = Record.objects.select_related('country', 'device')

    if check_user_full_permission(user):
        return qs

    paises_ids = CountryPermission.objects.filter(
        user=user
    ).values_list('country_id', flat=True)

    is_semi_admin = user.groups.filter(name='Semi Admin').exists()

    if is_semi_admin:
        return qs.filter(country_id__in=paises_ids)

    nome_usuario = f"{user.first_name} {user.last_name}".strip() or user.username
    return qs.filter(
        country_id__in=paises_ids,
        responsible=nome_usuario
    )

from django.db.models import Count

def dashboard_responsavel(user, request, responsible=None, status=None, country=None):
    qs = base_queryset_por_usuario(user)

    # 🎯 Filtros
    if responsible:
        qs = qs.filter(responsible=responsible)

    if status:
        qs = qs.filter(status=status)

    if country:
        qs = qs.filter(country_id=country)

    # 📅 Filtro de data (centralizado)
    qs = aplicar_filtro_data(qs, request)

    # 📊 Agregação do dashboard
    return (
        qs.values(
            "responsible",
            "status",
            "country__name",
            "country_id",
        )
        .annotate(total=Count("id"))
        .order_by("responsible", "status", "country__name")
    )


def dashboard_por_status(user, request, status):
    qs = base_queryset_por_usuario(user)
    qs = aplicar_filtro_data(qs, request)

    return (
        qs.filter(status=status)
        .values('responsible')
        .annotate(total=Count('id'))
        .order_by('-total')
    )


def dashboard_por_pais(user, country_id):
    qs = base_queryset_por_usuario(user)

    return (
        qs.filter(country_id=country_id)
        .values('responsible', 'status')
        .annotate(total=Count('id'))
        .order_by('responsible')
    )

def lista_detalhada(user, request, responsible=None, status=None, country=None):
    qs = base_queryset_por_usuario(user)

    if responsible:
        qs = qs.filter(responsible=responsible)

    if status:
        qs = qs.filter(status=status)

    if country:
        qs = qs.filter(country_id=country)

    qs = aplicar_filtro_data(qs, request)

    return qs.select_related("country", "device").order_by("responsible", "-data")
