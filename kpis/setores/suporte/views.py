import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from ...models import KpiRegistroMensal
from usuarios.models import UsuarioProfile
from .services import (
    delete_monthly_record,
    get_monthly_records,
    get_monthly_summary,
    get_time_series,
    get_yearly_summary,
    list_technicians,
    upsert_monthly_record,
    get_equipamentos_summary,
    get_range_summary,
    get_all_time_series
)

def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _json_body(request: HttpRequest):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}

@login_required
def dashboard_kpis(request):
    perfil = request.user.profile
    is_master = perfil.role in ['dono', 'diretor'] or perfil.setor == 'ti'
    setores_com_kpi = ['suporte', 'comercial', 'marketing']

    if is_master:
        setor_req = request.GET.get("setor")
        if setor_req in setores_com_kpi:
            setor_ativo = setor_req
        else:
            setor_ativo = perfil.setor if perfil.setor in setores_com_kpi else "suporte"
    else:
        setor_ativo = perfil.setor

    today = date.today()
    year = _to_int(request.GET.get("ano"), today.year)
    month = _to_int(request.GET.get("mes"), today.month)

    context = {
        "setor_ativo": setor_ativo,
        "is_master": is_master,
        "ano": year,
        "mes": month,
        "anos": list(range(today.year - 5, today.year + 1)),
        "meses": list(range(1, 13)),
    }
    
    if setor_ativo == 'suporte':
        return render(request, "kpis/suporte/dashboard_suporte.html", context)
    elif setor_ativo == 'comercial':
        return render(request, "kpis/comercial/dashboard_comercial.html", context)
    elif setor_ativo == 'marketing':
        return render(request, "kpis/marketing/dashboard_marketing.html", context)
    else:
        return render(request, "kpis/sem_kpi.html", context)

@login_required
def entrada_kpis(request):
    today = date.today()
    year = _to_int(request.GET.get("ano"), today.year)
    month = _to_int(request.GET.get("mes"), today.month)
    context = {"ano": year, "mes": month, "anos": list(range(today.year - 5, today.year + 1)), "meses": list(range(1, 13))}
    return render(request, "kpis/suporte/entrada_suporte.html", context)

@login_required
@require_GET
def api_technicians_list(request):
    include_inactive = str(request.GET.get("include_inactive", "")).lower() in ("1", "true", "yes")
    perfis = list_technicians(include_inactive=include_inactive)
    data = [
        {"id": p.id, "name": p.user.get_full_name() or p.user.username, "category": p.area, "active": p.user.is_active}
        for p in perfis
    ]
    return JsonResponse(data, safe=False)

@login_required
@require_POST
def api_technicians_add(request):
    return JsonResponse({"ok": False, "message": "A criação de técnicos agora é feita no painel de Gestão."}, status=400)

@login_required
@require_POST
def api_technicians_toggle_active(request, tecnico_id):
    return JsonResponse({"ok": False, "message": "A ativação de usuários agora é feita no painel de Gestão."}, status=400)

@login_required
@require_GET
def api_records_by_month(request):
    today = date.today()
    year = _to_int(request.GET.get("year"), today.year)
    month = _to_int(request.GET.get("month"), today.month)
    records = get_monthly_records(year, month)
    data = [
        {"id": r.id, "technicianId": r.perfil_id, "technicianName": r.perfil.user.get_full_name() or r.perfil.user.username,
         "category": r.perfil.area, "year": r.ano, "month": r.mes, "totalAtendimentos": r.total_atendimentos, "notaMedia": float(r.nota_media)}
        for r in records
    ]
    return JsonResponse(data, safe=False)

@login_required
@require_POST
def api_records_upsert(request):
    payload = _json_body(request)
    technician_id = _to_int(payload.get("technicianId"))
    year = _to_int(payload.get("year"))
    month = _to_int(payload.get("month"))
    total_atendimentos = _to_int(payload.get("totalAtendimentos"), 0)

    try:
        nota_media = Decimal(str(payload.get("notaMedia", "0")))
    except (InvalidOperation, TypeError, ValueError):
        return JsonResponse({"ok": False, "message": "Nota média inválida."}, status=400)

    if not technician_id or not year or not month or month < 1 or month > 12 or total_atendimentos < 0 or not (0 <= nota_media <= 10):
        return JsonResponse({"ok": False, "message": "Dados inválidos enviados."}, status=400)

    if not UsuarioProfile.objects.filter(id=technician_id, setor=UsuarioProfile.Setor.SUPORTE).exists():
        return JsonResponse({"ok": False, "message": "Técnico não encontrado."}, status=404)

    record = upsert_monthly_record(tecnico_id=technician_id, year=year, month=month, total_atendimentos=total_atendimentos, nota_media=nota_media)
    return JsonResponse({"ok": True, "id": record.id})

@login_required
@require_POST
def api_records_delete(request, record_id):
    if not KpiRegistroMensal.objects.filter(id=record_id).exists():
        return JsonResponse({"ok": False, "message": "Registro não encontrado."}, status=404)
    delete_monthly_record(record_id)
    return JsonResponse({"ok": True})

@login_required
@require_GET
def api_kpi_summary(request):
    today = date.today()
    year = _to_int(request.GET.get("year"), today.year)
    month = _to_int(request.GET.get("month"), today.month)
    return JsonResponse(get_monthly_summary(year, month))

@login_required
@require_GET
def api_kpi_summary_by_year(request):
    today = date.today()
    year = _to_int(request.GET.get("year"), today.year)
    return JsonResponse(get_yearly_summary(year))

@login_required
@require_GET
def api_kpi_time_series(request):
    year = _to_int(request.GET.get("year"), date.today().year)
    tecnico_id = _to_int(request.GET.get("tecnico_id"))
    data = get_time_series(year, tecnico_id)
    return JsonResponse(data, safe=False)

@login_required
@require_GET
def api_equipamentos_summary(request):
    today = date.today()
    start_year = _to_int(request.GET.get("start_year"), today.year)
    start_month = _to_int(request.GET.get("start_month"), today.month)
    end_year = _to_int(request.GET.get("end_year"), start_year)
    end_month = _to_int(request.GET.get("end_month"), start_month)
    data = get_equipamentos_summary(start_year, start_month, end_year, end_month)
    return JsonResponse(data)

@login_required
def dashboard_equipamentos(request):
    perfil = request.user.profile
    is_master = perfil.role in ['dono', 'diretor'] or perfil.setor == 'ti'
    if perfil.role == 'colaborador' and not is_master:
        return redirect('painel_dashboard')
    if not is_master and perfil.setor != 'suporte':
        return redirect('painel_dashboard')
        
    year = _to_int(request.GET.get("ano"), date.today().year)
    month = _to_int(request.GET.get("mes"), date.today().month)
    return render(request, "kpis/suporte/equipamentos.html", {"ano": year, "mes": month})

@login_required
@require_GET
def api_kpi_summary_range(request):
    today = date.today()
    start_year = _to_int(request.GET.get("start_year"), today.year)
    start_month = _to_int(request.GET.get("start_month"), today.month)
    end_year = _to_int(request.GET.get("end_year"), start_year)
    end_month = _to_int(request.GET.get("end_month"), start_month)
    
    tecnico_id = _to_int(request.GET.get("tecnico_id"))
    
    data = get_range_summary(start_year, start_month, end_year, end_month, tecnico_id)
    return JsonResponse(data)

@login_required
@require_GET
def api_kpi_all_time_series(request):
    tecnico_id = _to_int(request.GET.get("tecnico_id"))
    data = get_all_time_series(tecnico_id)
    return JsonResponse(data, safe=False)