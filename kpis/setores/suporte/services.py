import calendar
from decimal import Decimal
from typing import Any
from django.db.models import Sum, F
from django.db.models.functions import Upper, Trim
from datetime import date

from situacao_veiculo.models import Cliente
from ...models import KpiRegistroMensal
from usuarios.models import UsuarioProfile 

MONTH_NAMES = [
    "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
    "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO",
]

def calc_working_days(year: int, month: int) -> int:
    days_in_month = calendar.monthrange(year, month)[1]
    working_days = 0
    for day in range(1, days_in_month + 1):
        weekday = calendar.weekday(year, month, day)
        if weekday < 5:
            working_days += 1
    return working_days

def _month_label(month: int) -> str:
    return MONTH_NAMES[month - 1]

def list_technicians(include_inactive: bool = False):
    qs = UsuarioProfile.objects.filter(setor=UsuarioProfile.Setor.SUPORTE).select_related('user')
    if not include_inactive:
        qs = qs.filter(user__is_active=True)
    return qs.order_by('user__first_name', 'user__username')

def get_monthly_records(year: int, month: int):
    return (
        KpiRegistroMensal.objects.select_related("perfil__user")
        .filter(ano=year, mes=month)
        .order_by("-total_atendimentos", "perfil__user__first_name")
    )

def get_yearly_records(year: int):
    return (
        KpiRegistroMensal.objects.select_related("perfil__user")
        .filter(ano=year)
        .order_by("mes", "perfil__user__first_name")
    )

def get_all_time_records():
    return (
        KpiRegistroMensal.objects.values("ano", "mes")
        .annotate(total_atendimentos=Sum("total_atendimentos"))
        .order_by("ano", "mes")
    )

def upsert_monthly_record(*, tecnico_id: int, year: int, month: int, total_atendimentos: int, nota_media: Decimal | float | str):
    obj, _ = KpiRegistroMensal.objects.update_or_create(
        perfil_id=tecnico_id,
        ano=year,
        mes=month,
        defaults={
            "total_atendimentos": total_atendimentos,
            "nota_media": Decimal(str(nota_media)),
        },
    )
    return obj

def delete_monthly_record(record_id: int):
    KpiRegistroMensal.objects.filter(id=record_id).delete()

def _serialize_record(record: KpiRegistroMensal) -> dict[str, Any]:
    if not record.perfil:
        return {
            "id": record.id,
            "technicianId": 0,
            "technicianName": "Usuário Excluído / Órfão",
            "category": "Desconhecida",
            "year": record.ano,
            "month": record.mes,
            "totalAtendimentos": record.total_atendimentos,
            "notaMedia": float(record.nota_media),
        }
    nome = record.perfil.user.get_full_name() or record.perfil.user.username
    return {
        "id": record.id,
        "technicianId": record.perfil_id,
        "technicianName": nome,
        "category": record.perfil.area,
        "year": record.ano,
        "month": record.mes,
        "totalAtendimentos": record.total_atendimentos,
        "notaMedia": float(record.nota_media),
    }

def _build_kpi_summary_from_items(records: list[dict[str, Any]], working_days: int):
    chaveiros = [r for r in records if r["category"] == UsuarioProfile.AreaSuporte.CHAVEIRO]
    diagnostico = [r for r in records if r["category"] == UsuarioProfile.AreaSuporte.DIAGNOSTICO]

    total_chaveiro = sum(r["totalAtendimentos"] for r in chaveiros)
    total_diagnostico = sum(r["totalAtendimentos"] for r in diagnostico)
    total_geral = total_chaveiro + total_diagnostico

    nota_geral_media = (
        sum(float(r["notaMedia"]) * r["totalAtendimentos"] for r in records) / total_geral
        if total_geral > 0 else 0
    )

    nota_geral_acumulada = (
        sum(float(r["notaMedia"]) for r in records) / len(records)
        if records else 0
    )

    media_atendimento_diario = (total_geral / working_days) if working_days > 0 else 0

    # 🔥 TMA: Tempo Médio de Atendimento
    # Disponibilidade = Dias Úteis * 9 horas (8h-18h com 1h almoço)
    disponibilidade_horas = working_days * 9
    tma_minutos = (disponibilidade_horas * 60 / total_geral) if total_geral > 0 else 0

    champion = None
    if records:
        champion_raw = max(records, key=lambda r: r["totalAtendimentos"])
        champion = {
            "name": champion_raw["technicianName"],
            "totalAtendimentos": champion_raw["totalAtendimentos"],
            "nota": float(champion_raw["notaMedia"]),
        }

    per_technician = []
    for r in records:
        per_technician.append({
            "id": r["technicianId"],
            "name": r["technicianName"],
            "category": r["category"],
            "totalAtendimentos": r["totalAtendimentos"],
            "notaMedia": float(r["notaMedia"]),
            "mediaAtendimentoDiario": round((r["totalAtendimentos"] / working_days) if working_days > 0 else 0, 1),
        })

    return {
        "totalAtendimentos": total_geral,
        "totalChaveiro": total_chaveiro,
        "totalDiagnostico": total_diagnostico,
        "notaGeralMedia": round(nota_geral_media, 2),
        "notaGeralAcumulada": round(nota_geral_acumulada, 2),
        "mediaAtendimentoDiario": round(media_atendimento_diario, 1),
        "tmaMinutos": round(tma_minutos, 1),
        "workingDays": working_days,
        "champion": champion,
        "perTechnician": per_technician,
        "chaveiros": [{"id": r["technicianId"], "name": r["technicianName"], "totalAtendimentos": r["totalAtendimentos"], "notaMedia": float(r["notaMedia"])} for r in chaveiros],
        "diagnostico": [{"id": r["technicianId"], "name": r["technicianName"], "totalAtendimentos": r["totalAtendimentos"], "notaMedia": float(r["notaMedia"])} for r in diagnostico],
    }

def get_monthly_summary(year: int, month: int):
    records = [_serialize_record(r) for r in get_monthly_records(year, month)]
    working_days = calc_working_days(year, month)
    summary = _build_kpi_summary_from_items(records, working_days)
    summary["periodLabel"] = f"{_month_label(month)} {year}"
    summary["year"] = year
    summary["month"] = month
    return summary

def get_yearly_summary(year: int):
    records_qs = get_yearly_records(year)
    now = date.today()
    last_month = now.month if year == now.year else 12

    raw_records = [_serialize_record(r) for r in records_qs if r.mes <= last_month]
    aggregated: dict[int, dict[str, Any]] = {}

    for record in raw_records:
        technician_id = record["technicianId"]
        nota_value = float(record["notaMedia"])

        if technician_id not in aggregated:
            aggregated[technician_id] = {
                "technicianId": technician_id,
                "technicianName": record["technicianName"],
                "category": record["category"],
                "year": year,
                "month": last_month,
                "totalAtendimentos": 0,
                "weightedNota": 0.0,
                "monthCount": 0,
            }

        aggregated[technician_id]["totalAtendimentos"] += record["totalAtendimentos"]
        aggregated[technician_id]["weightedNota"] += nota_value * record["totalAtendimentos"]
        aggregated[technician_id]["monthCount"] += 1

    aggregated_records: list[dict[str, Any]] = []
    for item in aggregated.values():
        total = item["totalAtendimentos"]
        nota_media = (item["weightedNota"] / total) if total > 0 else 0
        aggregated_records.append({
            "technicianId": item["technicianId"],
            "technicianName": item["technicianName"],
            "category": item["category"],
            "year": year,
            "month": last_month,
            "totalAtendimentos": total,
            "notaMedia": nota_media,
        })

    aggregated_records.sort(key=lambda x: x["totalAtendimentos"], reverse=True)
    working_days = sum(calc_working_days(year, m) for m in range(1, last_month + 1))
    summary = _build_kpi_summary_from_items(aggregated_records, working_days)

    if last_month == 12:
        period_label = "Janeiro a Dezembro"
    else:
        period_label = f"Janeiro a {_month_label(last_month).title()}"

    summary["workingDays"] = working_days
    summary["monthsIncluded"] = last_month
    summary["periodLabel"] = period_label
    summary["year"] = year
    return summary

def get_range_summary(start_year: int, start_month: int, end_year: int, end_month: int, tecnico_id: int = None):
    start_val = start_year * 100 + start_month
    end_val = end_year * 100 + end_month
    
    records_qs = KpiRegistroMensal.objects.select_related("perfil__user").annotate(
        periodo=F('ano') * 100 + F('mes')
    ).filter(
        periodo__gte=start_val,
        periodo__lte=end_val
    )
    
    # === TRAVA INDIVIDUAL ===
    if tecnico_id:
        records_qs = records_qs.filter(perfil_id=tecnico_id)
    
    raw_records = [_serialize_record(r) for r in records_qs]
    aggregated: dict[int, dict[str, Any]] = {}
    
    for record in raw_records:
        t_id = record["technicianId"]
        nota_value = float(record["notaMedia"])
        
        if t_id not in aggregated:
            aggregated[t_id] = {
                "technicianId": t_id,
                "technicianName": record["technicianName"],
                "category": record["category"],
                "totalAtendimentos": 0,
                "weightedNota": 0.0,
            }
            
        aggregated[t_id]["totalAtendimentos"] += record["totalAtendimentos"]
        aggregated[t_id]["weightedNota"] += nota_value * record["totalAtendimentos"]
        
    aggregated_records: list[dict[str, Any]] = []
    for item in aggregated.values():
        total = item["totalAtendimentos"]
        nota_media = (item["weightedNota"] / total) if total > 0 else 0
        aggregated_records.append({
            "technicianId": item["technicianId"],
            "technicianName": item["technicianName"],
            "category": item["category"],
            "totalAtendimentos": total,
            "notaMedia": round(nota_media, 2),
        })
        
    aggregated_records.sort(key=lambda x: x["totalAtendimentos"], reverse=True)
    
    working_days = 0
    for y in range(start_year, end_year + 1):
        m_start = start_month if y == start_year else 1
        m_end = end_month if y == end_year else 12
        for m in range(m_start, m_end + 1):
            working_days += calc_working_days(y, m)
            
    summary = _build_kpi_summary_from_items(aggregated_records, working_days)
    return summary

def get_time_series(year: int, tecnico_id: int = None):
    qs = KpiRegistroMensal.objects.filter(ano=year).values('ano', 'mes')
    
    # === TRAVA INDIVIDUAL ===
    if tecnico_id:
        qs = qs.filter(perfil_id=tecnico_id)
        
    qs = qs.annotate(
        total_atendimentos_sum=Sum('total_atendimentos')
    ).order_by('ano', 'mes')
    
    return [
        {
            "year": row["ano"],
            "month": row["mes"],
            "totalAtendimentos": row["total_atendimentos_sum"] or 0,
        }
        for row in qs
    ]

def get_all_time_series(tecnico_id: int = None):
    qs = KpiRegistroMensal.objects.values('ano', 'mes')
    
    # === TRAVA INDIVIDUAL ===
    if tecnico_id:
        qs = qs.filter(perfil_id=tecnico_id)
        
    qs = qs.annotate(
        total_atendimentos_sum=Sum('total_atendimentos')
    ).order_by('ano', 'mes')
    
    return [
        {
            "year": item['ano'],
            "month": item['mes'],
            "totalAtendimentos": item['total_atendimentos_sum'] or 0
        }
        for item in qs
    ]

def get_equipamentos_summary(start_year: int, start_month: int, end_year: int, end_month: int):
    # Restante da função que já estava boa...
    equipamentos_raw = [
        "EAATA 360 PRO", "EAATA360 PRO", 
        "THINKTOOL MASTER 2", "master 2", "THINKCAR Master 2", 
        "VENU 90", 
        "THINKCAR TWAND 900", 
        "THINKCAR TWAND 200", 
        "EAATA90", 
        "Thinkcar MAX", "THINKCAR MAX", "THINK CAR MAX", "THINKTOOL MAX",
        "THINKTOOL EXPERT 399", 
        "THINKTOOL READER HD", 
        "THINKTOOL EXPERT 394", 
        "THINKTOOL MASTER X", "Thinkcar Master"
    ]
    equipamentos_alvo = [e.strip().upper() for e in equipamentos_raw]

    start_date = date(start_year, start_month, 1)
    _, last_day = calendar.monthrange(end_year, end_month)
    end_date = date(end_year, end_month, last_day)

    qs = Cliente.objects.annotate(
        equip_limpo=Upper(Trim('equipamento'))
    ).filter(
        equip_limpo__in=equipamentos_alvo,
        data__lte=end_date
    ).order_by('-data')

    total_maquinas = qs.count()
    ativos, a_vencer, vencidos, bloqueados, novos = 0, 0, 0, 0, 0
    lista_clientes = []

    for c in qs:
        status = c.status
        c_venc = c.vencimento.date() if hasattr(c.vencimento, 'date') else c.vencimento
        c_data = c.data.date() if hasattr(c.data, 'date') else c.data
        
        in_venc_range = bool(c_venc and start_date <= c_venc <= end_date)
        in_creation_range = bool(c_data and start_date <= c_data <= end_date)

        if in_creation_range: novos += 1

        if status == 'direito':
            ativos += 1
            status_label = "Ativo"
        elif status == 'vencendo':
            status_label = "A Vencer"
            if in_venc_range: a_vencer += 1
        elif status == 'vencido':
            status_label = "Vencido"
            if in_venc_range: vencidos += 1
        elif status in ['bloqueado', 'bloqueado_data_invalida']:
            bloqueados += 1
            status_label = "Bloqueado"
        else:
            status_label = "Indefinido"

        equip_raw = c.equipamento or "-"
        equip_upper = equip_raw.strip().upper()

        if equip_upper in ["EAATA 360 PRO", "EAATA360 PRO"]: equip_padrao = "EAATA 360 PRO"
        elif equip_upper in ["THINKTOOL MASTER 2", "MASTER 2", "THINKCAR MASTER 2"]: equip_padrao = "THINKTOOL MASTER 2"
        elif equip_upper in ["THINKCAR MAX", "THINK CAR MAX", "THINKTOOL MAX"]: equip_padrao = "THINKTOOL MAX"
        elif equip_upper in ["THINKTOOL MASTER X", "THINKCAR MASTER"]: equip_padrao = "THINKTOOL MASTER X"
        elif equip_upper == "EAATA90": equip_padrao = "EAATA 90"
        else: equip_padrao = equip_upper

        lista_clientes.append({
            "nome": c.nome or "Sem Nome",
            "equipamento": equip_padrao,
            "status": status_label,
            "data": c.data.strftime("%d/%m/%Y") if c.data else "-",
            "vencimento": c.vencimento.strftime("%d/%m/%Y") if c.vencimento else "-",
            "in_venc_range": in_venc_range,
            "in_creation_range": in_creation_range
        })

    return {
        "total_maquinas": total_maquinas,
        "suportes_ativos": ativos,
        "suportes_vencidos": vencidos,
        "suportes_a_vencer": a_vencer,
        "suportes_bloqueados": bloqueados,
        "novos_clientes": novos,
        "clientes": lista_clientes,
    }