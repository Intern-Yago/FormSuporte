# -*- coding: utf-8 -*-
from datetime import datetime, date
from collections import defaultdict
import os
import json
import mimetypes
from django.conf import settings
import requests
from datetime import timedelta

from ocorrencia_erro.utils.adminlog import add_admin_log
from painel.decorators import require_system_access
from utils.weasyprint_loader import configure_weasyprint
configure_weasyprint()

from langdetect import detect, DetectorFactory
DetectorFactory.seed = 0

from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from django.db.models import Q
from django.core.paginator import Paginator
from django.urls import reverse
from django.contrib.auth import authenticate, login as login_django, logout as logout_django
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

User = get_user_model()
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.serializers import serialize
from django.db import IntegrityError
from django.http import FileResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, mm
import io
from django.views.decorators.http import require_http_methods
import json
import re
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
import zipfile
from django.utils.encoding import smart_str
from time import timezone
from django.utils.translation import gettext as _

from django.views.decorators.http import require_POST
from .models import Record, ChatMessage, RecordStatusLog
from utils.chat_media import base64_to_contentfile

from ocorrencia_erro.services.dashboard import (
    dashboard_responsavel,
    dashboard_por_status,
    dashboard_por_pais,
    lista_detalhada
)
from ocorrencia_erro.services.dashboard import dashboard_responsavel

from django.template.loader import render_to_string
from django.http import HttpResponse
from django.utils import timezone
from weasyprint import HTML

from ocorrencia_erro.services.dashboard import dashboard_responsavel
from .models import Record, Country, CountryPermission, Device, ArquivoOcorrencia, Notificacao, OptionItem, ChatMessage

def create_movement_log(
    *,
    record,
    user,
    event_type,
    field=None,
    from_status=None,
    to_status=None,
    note=None,
    dedupe_seconds=2,
):
    """
    Cria log de movimentação com dedupe simples.
    Se o frontend disparar duas vezes a mesma alteração, a segunda é ignorada.
    """
    qs = RecordStatusLog.objects.filter(
        record=record,
        user=user if (user and user.is_authenticated) else None,
        event_type=event_type,
        field=field,
        from_status=from_status,
        to_status=to_status,
        note=note,
    ).order_by("-id")

    last = qs.first()
    if last:
        delta = timezone.now() - last.created_at
        if delta.total_seconds() <= dedupe_seconds:
            return last  # ignora duplicado

    return RecordStatusLog.objects.create(
        record=record,
        user=user if (user and user.is_authenticated) else None,
        event_type=event_type,
        field=field,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )

# Constantes
DATE_COLUMNS = ["data", "deadline", "finished"]
STATUS_OCORRENCIA = {
    'Concluído': 'DONE',
    'Atrasado': 'LATE',
    'Em progresso': 'PROGRESS',
    'Requisitado': 'REQUESTED',
    'Aguardando China': 'AWAITING_CHINA',
    'China Atrasada': 'AWAITING_CHINA_LATE', # Adicionado novo status
}
STATUS_MAP_REVERSED = {v: k for k, v in STATUS_OCORRENCIA.items()}

# Problemas padrão por área (usados ao criar um novo SISTEMA)
# Mantém alinhado com as seeds de migração (0004_seed_problem_by_system)
DEFAULT_PROBLEMS_BY_AREA = {
    'IMMO': [
        'Tradução',
        'DTC Errado',
        'DTC Sem Texto',
        'Não Apaga DTC',
        'Não le DTC',
        'Não Le PIN',
        'Erro CHIP - Chave',
        'Não Comunica',
        'Informação Errada (INFO)',
        'Falta Função',
        'Senha ERRADA',
        'Dados Errados - (IMMO)',
        'Parâmetro - (Errado)',
        'Não Programa Controle',
    ],
    'Diagnosis': [
        'Tradução',
        'DTC Errado',
        'DTC Sem Texto',
        'Não Apaga DTC',
        'Não le DTC',
        'Não Reseta Revisão',
        'Não Reseta Parametro',
        'Ajuste Basico',
        'Não Executa Função',
        'Não Programa Chave',
        'Não Le PIN',
        'Erro CHIP - Chave',
        'Não Comunica',
        'Informação Errada (INFO)',
        'Falta Função',
        'Não Recua Pinça',
        'Ângulo Direção',
        'Senha ERRADA',
        'Dados Errados - (IMMO)',
        'Parâmetro - (Errado)',
        'Não Programa Controle',
    ],
}

ALLOWED_SORT_COLUMNS = [
    'feedback_manager', 'feedback_technical', 'problem_detected', 'area', 'sistema', 'tipo_problema', 'brand',
    'country', 'data', 'deadline', 'device', 'finished', 'model', 'responsible',
    'serial', 'status', 'technical', 'version', 'year'
]

FILTERABLE_COLUMNS_FOR_OPTIONS = [
    'id','technical', 'country', 'device', 'area', 'sistema', 'tipo_problema', 'serial', 'brand',
    'model', 'year', 'version', 'status', 'responsible',
    'data', 'deadline', 'finished'
]

URL_LOGIN = 'subir_ocorrencia'

@login_required(login_url=settings.URL_LOGIN)
@require_POST
@require_system_access("ocorrencia")
def upload_chat_image(request, record_id):
    record = get_object_or_404(Record, id=record_id)

    # você pode reaproveitar sua regra de permissão por país aqui
    # (igual você já faz no download_arquivo)

    data_url = request.POST.get("image_base64") or ""
    original_name = request.POST.get("image_name") or "chat-image"

    content_file, _mime = base64_to_contentfile(data_url, fallback_name=original_name)
    if not content_file:
        return JsonResponse({"ok": False, "error": "imagem inválida"}, status=400)

    msg = ChatMessage.objects.create(
        record=record,
        author=request.user,
        message=request.POST.get("message", "") or "",
    )
    msg.image.save(content_file.name, content_file, save=True)

    # ✅ opcional: não guardar base64 (economiza DB)
    msg.image_base64 = ""
    msg.image_type = ""
    msg.image_name = ""
    msg.save(update_fields=["image_base64", "image_type", "image_name"])

    return JsonResponse({
        "ok": True,
        "id": msg.id,
        "image_url": msg.image.url,
        "timestamp": msg.timestamp.isoformat(),
        "author": request.user.username,
        "message": msg.message,
    })

from ocorrencia_erro.utils.permissions import check_user_full_permission

def detectar_idioma(texto):
    if not texto or len(texto.strip()) < 3:  # textos muito curtos
        return 'PT'  # fallback
    try:
        return detect(texto).upper()  # retorna 'PT', 'ES', 'EN', etc.
    except:
        return 'PT'

@require_http_methods(['POST'])
def traduzir_api(request):
    """
    Reutiliza a função traduzir_texto() para traduzir textos via requisição JS.
    """

    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
        texto = data.get("texto", "")
        print(texto)
        if not texto:
            return JsonResponse({"error": "Texto vazio"}, status=400)

        # ✅ Aqui reaproveita sua função SEM alterar nada
        traduzido = traduzir_texto(texto)

        return JsonResponse({"traduzido": traduzido})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def traduzir_texto(texto, target_lang='EN-US', api_key='71437a8a-e2de-43da-a9d7-ef10bd2550cf:fx'):
    """
    Traduz texto curto ou longo para inglês usando DeepL Free.
    Suporta string única ou lista de strings para tradução em lote.
    Utiliza autenticação baseada em Header (exigência DeepL Nov/2025).
    """
    if not texto:
        return "N/A" if not isinstance(texto, list) else []

    url = "https://api-free.deepl.com/v2/translate"
    headers = {
        "Authorization": f"DeepL-Auth-Key {api_key}"
    }
    
    # Se for uma lista, preparamos os múltiplos parâmetros 'text'
    if isinstance(texto, (list, tuple)):
        payload = [('target_lang', target_lang)]
        for t in texto:
            payload.append(('text', t or "N/A"))
    else:
        if str(texto).strip().upper() in ["N/A", "NÃO IDENTIFICADO", ""]:
            return "N/A"
        payload = {
            "text": texto,
            "target_lang": target_lang,
        }

    try:
        # DeepL exige form-data ou query params, mas a chave DEVE estar no Header agora
        response = requests.post(url, data=payload, headers=headers, timeout=20)
        response.raise_for_status()
        result = response.json()
        
        if isinstance(texto, (list, tuple)):
            return [t['text'] for t in result['translations']]
        return result['translations'][0]['text']
    except Exception as e:
        print(f"Erro na tradução DeepL (Header Auth): {e}")
        return texto

def get_responsaveis():
    paises = Country.objects.all().order_by('name')
    responsaveis_por_pais = {}
    todos_responsaveis = []
    
    # Buscar o grupo "Técnicos responsáveis"
    try:
        grupo_tecnicos = Group.objects.get(name='Técnicos responsáveis')
    except Group.DoesNotExist:
        # Se o grupo não existir, retorna estruturas vazias
        return json.dumps({}), json.dumps([])
    
    # Buscar apenas usuários que são técnicos responsáveis E têm permissões de país
    usuarios_tecnicos = grupo_tecnicos.user_set.filter(
        country_permissions__isnull=False
    ).distinct().values('id', 'first_name', 'last_name', 'username')
    
    # Criar lista de todos os responsáveis (apenas técnicos)
    responsaveis_dict = {}
    for user in usuarios_tecnicos:
        nome_completo = f"{user['first_name']} {user['last_name']}".strip()
        if not nome_completo:
            nome_completo = user['username']
        
        responsavel_data = {
            'id': user['id'],
            'name': nome_completo
        }
        
        todos_responsaveis.append(responsavel_data)
        responsaveis_dict[user['id']] = responsavel_data
            
    # Mapear responsáveis por país usando CountryPermission (apenas técnicos)
    for pais in paises:
        # Buscar usuários técnicos que têm permissão neste país
        permissoes = CountryPermission.objects.filter(
            country=pais,
            user__groups=grupo_tecnicos  # Filtra apenas usuários do grupo técnicos
        ).select_related('user')
        
        responsaveis_por_pais[pais.name] = []
        for permissao in permissoes:
            user = permissao.user
            nome_completo = f"{user.first_name} {user.last_name}".strip()
            if not nome_completo:
                nome_completo = user.username
            
            responsaveis_por_pais[pais.name].append({
                'name': nome_completo,
            })
    
    responsaveis_por_pais_json = json.dumps(responsaveis_por_pais)
    todos_responsaveis_json = json.dumps(todos_responsaveis)
    return (responsaveis_por_pais_json, todos_responsaveis_json)

def subir_arquivo(files, record):
    for file in files:
        # Extrai a extensão do arquivo original
        ext = os.path.splitext(file.name)[1]  # inclui o ponto, ex: ".jpg"

        # Define o novo nome do arquivo
        novo_nome = file.name

        # Cria o registro no banco
        ArquivoOcorrencia.objects.create(
            record=record,
            arquivo=file,
            nome_original=novo_nome  # ou mantenha file.name se preferir
        )

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def download_todos_arquivos(request, record_id):
    record = get_object_or_404(Record, id=record_id)
    # Usuários de leitura (reporte/concluído) só podem baixar arquivos de ocorrências concluídas
    if (request.user.groups.filter(name='Somente Concluído').exists() or
        request.user.groups.filter(name='Técnicos de reporte').exists()) and record.status != Record.STATUS_OCORRENCIA.DONE:
        raise Http404("Arquivo não encontrado ou sem permissão")
    arquivos = ArquivoOcorrencia.objects.filter(record=record)

    print(arquivos)

    if not arquivos.exists():
        return JsonResponse({'status': 'error', 'message': 'Nenhum arquivo encontrado.'}, status=404)

    if arquivos.count() <= 1:
        # Retorna múltiplos arquivos, mas um por vez via response streaming
        # (normalmente o ideal é baixar em ZIP também, mas mantendo a regra)
        arquivo = arquivos.first()
        response = FileResponse(arquivo.arquivo.open("rb"), as_attachment=True, filename=arquivo.nome_original)
        return response
    else:
        # Gera o zip temporário
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
            for arq in arquivos:
                nome = arq.nome_original or os.path.basename(arq.arquivo.name)
                with arq.arquivo.open("rb") as f:
                    zip_file.writestr(nome, f.read())


        zip_buffer.seek(0)

        response = HttpResponse(zip_buffer, content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename=arquivos_ocorrencia_{record.id}_{record.serial}.zip'
        return response


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def index(request):
    responsaveis_por_pais_json, todos_responsaveis_json = get_responsaveis()
    
    ocorrencias_queryset = Record.objects.all()
    user = request.user

    if not check_user_full_permission(user):
        # Usuário somente leitura de concluídos (reporte)
        is_view_done_only = (
            user.groups.filter(name='Somente Concluído').exists() or
            user.groups.filter(name='Técnicos de reporte').exists()
        )
        if is_view_done_only:
            paises_permitidos_ids = CountryPermission.objects.filter(user=user).values_list('country_id', flat=True)
            ocorrencias_queryset = Record.objects.filter(
                status=Record.STATUS_OCORRENCIA.DONE,
                country_id__in=list(paises_permitidos_ids)
            )

        else:
            paises_permitidos_ids = CountryPermission.objects.filter(user=user).values_list('country_id', flat=True)
            is_semi_admin = user.groups.filter(name='Semi Admin').exists()

            if is_semi_admin:
                ocorrencias_queryset = ocorrencias_queryset.filter(country_id__in=list(paises_permitidos_ids))
            else:
                nome_completo_usuario = f"{user.first_name} {user.last_name}".strip() or user.username
                ocorrencias_queryset = ocorrencias_queryset.filter(
                    Q(country_id__in=list(paises_permitidos_ids)) & 
                    Q(responsible=nome_completo_usuario)
                )

    status_map = {
        Record.STATUS_OCORRENCIA.DONE: _("Concluído"),
        Record.STATUS_OCORRENCIA.LATE: _("Atrasado"),
        Record.STATUS_OCORRENCIA.PROGRESS: _("Em progresso"),
        Record.STATUS_OCORRENCIA.REQUESTED: _("Requisitado"),
        Record.STATUS_OCORRENCIA.AWAITING_CHINA: _("Aguardando China"),
        Record.STATUS_OCORRENCIA.AWAITING_CHINA_LATE: _("China Atrasada"),

    }

    ocorrencias_dict = defaultdict(lambda: {label: 0 for label in status_map.values()})

    for record in ocorrencias_queryset.values('responsible', 'status'):
        nome = record['responsible']
        status_codigo = record['status']
        status_legivel = status_map.get(status_codigo)

        if nome and nome != "Não identificado" and status_legivel:
            ocorrencias_dict[nome][status_legivel] += 1

    ocorrencias_json = json.dumps(ocorrencias_dict, ensure_ascii=False)

    # --- INÍCIO DA ALTERAÇÃO NECESSÁRIA ---

    is_super = check_user_full_permission(user)
    # 1. Reutiliza a verificação de 'is_semi_admin' que já fizemos
    is_semi_admin = user.groups.filter(name='Semi Admin').exists() 
    is_somente_concluido = (
        user.groups.filter(name='Somente Concluído').exists() or
        user.groups.filter(name='Técnicos de reporte').exists()
    )
    
    # 2. Cria a nova variável de permissão
    has_edit_permission = is_super or is_semi_admin

    # --- FIM DA ALTERAÇÃO NECESSÁRIA ---

    if is_super or is_somente_concluido:
        permitted_countries = Country.objects.all().values_list('name', flat=True)
    else:
        permitted_countries = Country.objects.filter(
            id__in=CountryPermission.objects.filter(user=user).values_list('country_id', flat=True)
        ).values_list('name', flat=True)

    context = {
        'user': user,
        'paises_permitidos': list(permitted_countries),
        'has_full_permission': is_super,
        
        # 3. Adiciona a nova variável ao contexto para ser usada no template
        'has_edit_permission': has_edit_permission,
        'view_done_only': is_somente_concluido,
        
        'responsaveis_por_pais': responsaveis_por_pais_json,
        'todos_responsaveis': todos_responsaveis_json,
        'ocorrencias_json': ocorrencias_json,
    }
    return render(request, 'ocorrencia/index.html', context)

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def filter_data_view(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            filters = data.get('filters', {})
            sort_info = data.get('sort', {'column': 'data', 'direction': 'asc'})
            page_number = data.get('page', 1)
            
            global_search = data.get('global_search', '').strip() # <--- NOVO: Captura a busca global

            # 1. Consulta base otimizada
            base_queryset = Record.objects.select_related('device', 'country')
            
            user = request.user
            
            # --- INÍCIO DA DEPURAÇÃO ---
            print(f"--- Iniciando depuração para o usuário: {user.username} ---")
            
            if not check_user_full_permission(user):
                # 1. Quais países este usuário pode ver?
                is_somente_concluido = (
                    user.groups.filter(name='Somente Concluído').exists() or
                    user.groups.filter(name='Técnicos de reporte').exists()
                )
                if is_somente_concluido:
                    print("Usuário do grupo de leitura (reporte). Filtrando apenas status DONE, sem outras restrições.")
                    paises_permitidos_ids = CountryPermission.objects.filter(user=user).values_list('country_id', flat=True)
                    base_queryset = base_queryset.filter(
                        status=Record.STATUS_OCORRENCIA.DONE,
                        country_id__in=list(paises_permitidos_ids),
                    )
                    paises_permitidos_lista = list(paises_permitidos_ids)
                    is_semi_admin = False

                else:
                    paises_permitidos_ids = CountryPermission.objects.filter(user=user).values_list('country_id', flat=True)
                    paises_permitidos_lista = list(paises_permitidos_ids)
                    print(f"IDs dos países permitidos: {paises_permitidos_lista}")

                    # 2. O usuário é Semi Admin?
                    is_semi_admin = user.groups.filter(name='Semi Admin').exists()
                    print(f"É Semi Admin? {is_semi_admin}")
                
                # 3. Quais são TODOS os grupos do usuário?
                grupos_usuario = list(user.groups.all().values_list('name', flat=True))
                print(f"Grupos do usuário: {grupos_usuario}")

                if is_somente_concluido:
                    # Já filtrado por DONE acima
                    pass
                elif is_semi_admin or check_user_full_permission(user):
                    base_queryset = base_queryset.filter(country_id__in=paises_permitidos_lista)
                else:
                    nome_completo_usuario = f"{user.first_name} {user.last_name}".strip() or user.username
                    base_queryset = base_queryset.filter(
                        Q(country_id__in=paises_permitidos_lista) &
                        Q(responsible=nome_completo_usuario)
                    )
                
                print(f"Total de registros após filtro de permissão: {base_queryset.count()}")
            else:
                print("Usuário é Superuser. Nenhuma permissão aplicada.")
            
            print("--- Fim da depuração ---")
            # --- FIM DA DEPURAÇÃO ---
            # --- NOVO: APLICAÇÃO DA BUSCA GLOBAL ---
            if global_search:
                search_q = Q()
                # Lista de TODOS os campos texto onde queremos buscar
                TEXT_FIELDS = [
                    'codigo_externo', 'ticket_fabricante', 'technical', 'area', 'sistema',
                    'tipo_problema', 'serial', 'brand', 'model', 'version', 'responsible',
                    'problem_detected', 'solution', 'feedback_technical', 'feedback_manager',
                    'tipo_chave', 'device__name', 'country__name', 'parceiro', 'origem_ocorrencia'
                ]
                # Monta a query usando "OU" (|) para procurar em qualquer um deles
                for field in TEXT_FIELDS:
                    search_q |= Q(**{f'{field}__icontains': global_search})
                
                base_queryset = base_queryset.filter(search_q)
            # ----------------------------------------
            queryset = base_queryset
            options_queryset = base_queryset     

            # 2. Construção dos filtros selecionados pelo usuário na interface
            q_objects = Q()
            column_q_dict = {} # 🔥 NOVO: Dicionário para isolar as queries de cada coluna

            for column, values in filters.items():
                if not isinstance(values, list) or not values:
                    continue

                column_q = Q()
                has_empty = '' in values
                non_empty = [v.strip() for v in values if v != ""]

                TEXT_CASE_INSENSITIVE_COLUMNS = [
                    'codigo_externo', 'ticket_fabricante', 'technical', 'area', 'sistema', 'tipo_problema', 'serial', 'brand', 'model',
                    'version', 'responsible', 'problem_detected', 'feedback_technical',
                    'feedback_manager', 'tipo_chave'
                ]

                # Filtros para valores não vazios
                if non_empty:
                    print(column)
                    if column == 'status':
                        status_values = [STATUS_OCORRENCIA.get(v, v) for v in non_empty]
                        # Adiciona AWAITING_CHINA ao filtro se AWAITING for selecionado
                        if 'AWAITING' in status_values and 'AWAITING_CHINA' not in status_values:
                            status_values.append('AWAITING_CHINA')
                        column_q |= Q(status__in=status_values)
                    elif column in DATE_COLUMNS:
                        dates = []
                        for v in non_empty:
                            try:
                                if '/' in v:
                                    dt = datetime.strptime(v, '%d/%m/%Y').date()
                                else:
                                    dt = datetime.strptime(v, '%Y-%m-%d').date()
                                dates.append(dt)
                            except:
                                continue
                        if dates:
                            column_q |= Q(**{f'{column}__in': dates})
                    elif column == 'country':
                        country_q_objects = Q()
                        for val in non_empty:
                            country_q_objects |= Q(country__name__iexact=val.strip())
                        column_q |= country_q_objects
                    elif column == 'device':
                        device_q_objects = Q()
                        for val in non_empty:
                            device_q_objects |= Q(device__name__iexact=val.strip())
                        column_q |= device_q_objects
                    elif column == 'codigo_externo':
                        # ID filtra por codigo_externo OU ticket_fabricante
                        text_q_objects = Q()
                        for val in non_empty:
                            v = (val or "").strip()
                            if not v:
                                continue
                            text_q_objects |= (
                                Q(codigo_externo__icontains=v) |
                                Q(ticket_fabricante__icontains=v)
                            )
                        column_q |= text_q_objects

                    elif column in TEXT_CASE_INSENSITIVE_COLUMNS:
                        text_q_objects = Q()
                        for val in non_empty:
                            text_q_objects |= Q(**{f'{column}__icontains': val.strip()})
                        column_q |= text_q_objects

                    elif column in TEXT_CASE_INSENSITIVE_COLUMNS:
                        text_q_objects = Q()
                        for val in non_empty:
                            text_q_objects |= Q(**{f'{column}__icontains': val.strip()})
                        column_q |= text_q_objects
                    else:
                        column_q |= Q(**{f'{column}__in': non_empty})

                # Filtro para valores vazios/nulos
                if has_empty:
                    if column == 'country':
                        column_q |= Q(country__isnull=True)
                    elif column == 'device':
                        column_q |= Q(device__isnull=True)
                    elif column == 'codigo_externo':
                        column_q |= Q(codigo_externo__isnull=True)
                    else:
                        column_q |= Q(**{f'{column}__isnull': True}) | Q(**{f'{column}__exact': ''})

                if column_q:
                    q_objects &= column_q
                    column_q_dict[column] = column_q

            if q_objects:
                queryset = queryset.filter(q_objects)

            # 3. Ordenação
            sort_column = sort_info.get('column', 'data')
            sort_direction = sort_info.get('direction', 'desc')
            
            if sort_column in ALLOWED_SORT_COLUMNS:
                prefix = '-' if sort_direction == 'desc' else ''
                
                if sort_column == 'country':
                    queryset = queryset.order_by(f"{prefix}country__name")
                elif sort_column == 'device':
                    queryset = queryset.order_by(f"{prefix}device__name")
                elif sort_column == 'data':
                    # --- CORREÇÃO DE ORDENAÇÃO ---
                    # Ordena pela Data E pelo ID.
                    # Se houver registros no mesmo dia, o ID (que é sequencial e preciso)
                    # garante que o último criado fique no topo (se for desc) ou no fim (se for asc).
                    queryset = queryset.order_by(f"{prefix}data", f"{prefix}id")
                else:
                    queryset = queryset.order_by(f"{prefix}{sort_column}")

            # 4. Paginação
            paginator = Paginator(queryset, 15)
            page_obj = paginator.get_page(page_number)

            # 5. Preparação dos dados para a resposta JSON
            records_data = []
            for record in page_obj.object_list:
                record_data = {
                    'id': record.id,
                    'codigo_externo': record.codigo_externo or str(record.id),
                    'data': record.data,
                    'technical': record.technical or '',
                    'country': record.country.name if record.country else '',
                    
                    # --- ADICIONE ESTA LINHA ---
                    'country_id': record.country.id if record.country else None,
                    'is_awaiting_china_late': record.is_awaiting_china_late(),
                    'ticket_fabricante': record.ticket_fabricante or '',
                    # -------------------------
                    'origem_ocorrencia': record.origem_ocorrencia or '',
                    'parceiro': record.parceiro or '',

                    'device': record.device.name if record.device else '',
                    'area': record.area or '',
                    'serial': record.serial or '',
                    'vin': record.vin or '',
                    'tipo_ecu': record.tipo_ecu or '',
                    'tipo_motor': record.tipo_motor or '',
                    'sistema': record.sistema or '',
                    'tipo_problema': record.tipo_problema or '',
                    'detalhes_responsavel': record.detalhes_responsavel or '',
                    'brand': record.brand or '',
                    'model': record.model or '',
                    'contact': record.contact or '',
                    'year': record.year or '',
                    'version': record.version or '',
                    'tipo_chave': record.tipo_chave or '',
                    'problem_detected': record.problem_detected or '',
                    'solution': record.solution or '',
                    'status': STATUS_MAP_REVERSED.get(record.status, record.status or ''),

                    'status_display': STATUS_MAP_REVERSED.get(record.status, record.status or ''),
                    'status_code': record.status,

                    'deadline': record.deadline.strftime('%d/%m/%Y') if record.deadline else '',
                    'responsible': record.responsible or '',
                    'finished': record.finished.strftime('%d/%m/%Y') if record.finished else '',
                    'arquivos': [
                        {
                            'id': arquivo.id,
                            'record_id': arquivo.record.codigo_externo or str(arquivo.record_id),
                            'url': arquivo.arquivo.url,
                            'nome_original': arquivo.nome_original,
                            "data_upload": arquivo.data_upload.strftime("%d/%m/%Y %H:%M")
                        }
                        for arquivo in ArquivoOcorrencia.objects.filter(record=record)
                    ],
                }
                record_data['status'] = record_data['status_display']
                records_data.append(record_data)

            from django.db.models import Count

            FILTERABLE_COLUMNS_FOR_OPTIONS = [
                'codigo_externo', 'ticket_fabricante', 'technical', 'country', 'device', 'area', 'sistema', 'tipo_problema', 'serial', 'brand',
                'model', 'year', 'version', 'status', 'responsible',
                'data', 'deadline', 'finished'
            ]

            filter_options = {}
            filter_counts = {} # 🔥 Dicionário que vai guardar os números pro JS

            for col in FILTERABLE_COLUMNS_FOR_OPTIONS:
                # O SEGREDO: Aplicamos todos os filtros da tela, EXCETO o desta própria coluna (OR).
                col_specific_q = Q()
                for k, cq in column_q_dict.items():
                    if k != col:
                        col_specific_q &= cq
                
                # Base de dados focada apenas para renderizar e contar esta caixinha de filtro
                col_qs = base_queryset.filter(col_specific_q)
                
                counts_dict = {}

                if col == 'country':
                    aggs = col_qs.exclude(country__isnull=True).values('country__name').annotate(c=Count('id'))
                    opts = set()
                    for agg in aggs:
                        if agg['country__name']:
                            val = agg['country__name'].upper()
                            opts.add(val)
                            counts_dict[val] = agg['c']
                    filter_options[col] = sorted(list(opts))

                elif col == 'device':
                    aggs = col_qs.exclude(device__isnull=True).values('device__name').annotate(c=Count('id'))
                    opts = set()
                    for agg in aggs:
                        if agg['device__name']:
                            val = agg['device__name'].upper()
                            opts.add(val)
                            counts_dict[val] = agg['c']
                    filter_options[col] = sorted(list(opts))

                elif col == 'sistema':
                    aggs = col_qs.exclude(sistema__isnull=True).exclude(sistema__exact='').values('sistema').annotate(c=Count('id'))
                    record_opts = set()
                    for agg in aggs:
                        if agg['sistema']:
                            val = agg['sistema'].strip().upper()
                            record_opts.add(val)
                            counts_dict[val] = counts_dict.get(val, 0) + agg['c']

                    try:
                        config_opts = set(OptionItem.objects.filter(category='SISTEMA', active=True).values_list('label', flat=True).distinct())
                    except:
                        config_opts = set()

                    all_opts = sorted(list({opt.strip().upper() for opt in record_opts.union(config_opts) if opt}))
                    filter_options[col] = all_opts

                elif col == 'tipo_problema':
                    aggs = col_qs.exclude(tipo_problema__isnull=True).exclude(tipo_problema__exact='').values('tipo_problema').annotate(c=Count('id'))
                    record_opts = set()
                    for agg in aggs:
                        if agg['tipo_problema']:
                            val = agg['tipo_problema'].strip().upper()
                            record_opts.add(val)
                            counts_dict[val] = counts_dict.get(val, 0) + agg['c']

                    try:
                        config_opts = set(OptionItem.objects.filter(category='PROBLEMA', active=True).values_list('label', flat=True).distinct())
                    except:
                        config_opts = set()

                    all_opts = sorted(list({opt.strip().upper() for opt in record_opts.union(config_opts) if opt}))
                    filter_options[col] = all_opts

                elif col == 'status':
                    aggs = col_qs.values('status').annotate(c=Count('id'))
                    opts = set()
                    for agg in aggs:
                        if agg['status']:
                            display_name = STATUS_MAP_REVERSED.get(agg['status'], agg['status'])
                            opts.add(display_name)
                            
                            # 🔥 A MÁGICA AQUI: Converte a chave da contagem para MAIÚSCULO!
                            # Isso alinha o status com todas as outras colunas para o JS achar.
                            upper_key = display_name.upper()
                            counts_dict[upper_key] = counts_dict.get(upper_key, 0) + agg['c']

                    filter_options[col] = sorted(
                        list(opts),
                        key=lambda x: list(STATUS_OCORRENCIA.keys()).index(x) if x in STATUS_OCORRENCIA else float('inf')
                    )

                elif col in DATE_COLUMNS:
                    dates = col_qs.exclude(**{f'{col}__isnull': True}).values_list(col, flat=True).distinct()
                    aggs = col_qs.exclude(**{f'{col}__isnull': True}).values(col).annotate(c=Count('id'))
                    for agg in aggs:
                        dt = agg[col]
                        if dt:
                            dt_str = str(dt) if isinstance(dt, date) else str(datetime.strptime(str(dt), '%Y-%m-%d').date())
                            counts_dict[dt_str] = agg['c']

                    date_tree = defaultdict(lambda: defaultdict(list))
                    for dt in dates:
                        if dt:
                            try:
                                dt = dt if isinstance(dt, date) else datetime.strptime(str(dt), '%Y-%m-%d').date()
                                year = str(dt.year)
                                month = dt.strftime('%m')
                                day = dt.strftime('%d')
                                if day not in date_tree[year][month]:
                                    date_tree[year][month].append(day)
                            except:
                                continue
                    for year in date_tree:
                        for month in date_tree[year]:
                            date_tree[year][month] = sorted(date_tree[year][month])
                        date_tree[year] = dict(sorted(date_tree[year].items()))
                    filter_options[col] = dict(sorted(date_tree.items()))

                elif col == 'codigo_externo':
                    codigos = col_qs.exclude(codigo_externo__isnull=True).exclude(codigo_externo='').values_list('codigo_externo', flat=True)
                    tickets = col_qs.exclude(ticket_fabricante__isnull=True).exclude(ticket_fabricante='').values_list('ticket_fabricante', flat=True)
                    filter_options[col] = sorted(set([c.strip() for c in codigos if c] + [t.strip() for t in tickets if t]))

                else:
                    aggs = col_qs.exclude(**{f'{col}__isnull': True}).exclude(**{f'{col}__exact': ''}).values(col).annotate(c=Count('id'))
                    opts = set()
                    for agg in aggs:
                        if agg[col]:
                            val = agg[col].upper()
                            opts.add(val)
                            counts_dict[val] = counts_dict.get(val, 0) + agg['c']
                    filter_options[col] = sorted(list(opts))
                
                filter_counts[col] = counts_dict

            # 7. Resposta final
            return JsonResponse({
                'records': records_data,
                'filter_options': filter_options,
                'filter_counts': filter_counts, # 🔥 MANDA AS CONTAGENS PRO FRONT
                'num_pages': paginator.num_pages,
                'current_page': page_obj.number,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Método inválido'}, status=405)

def logout_view(request):
    logout_django(request)
    return redirect('subir_ocorrencia')


def login_view(request):
    if request.method == "GET":
        next_url = request.GET.get('next', None)
        context = {'next': next_url} if next_url else {}
        return render(request, 'ocorrencia/login.html', context)

    else:
        username = request.POST.get('country', '').strip().capitalize()
        password = request.POST.get('password', '')
        next_url = request.POST.get('next', None)

        user = authenticate(request, username=username, password=password)
        if user is None:
            user = authenticate(request, username=username.upper(), password=password)

        if user:
            login_django(request, user)
            return redirect(next_url) if next_url else redirect('ocorrencia_home')
        else:
            return redirect(reverse('login_ocorrencias'))


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def criar_usuario(request):
    try:
        if not request.user.is_superuser:
            return redirect('ocorrencia_home')

        paises_existentes = Country.objects.all().order_by('name')

        if request.method == "GET":
            return render(request, 'ocorrencia/criar_usuario.html', {'paises': paises_existentes})

        if request.method == "POST":
            username = request.POST.get('username', '').strip().capitalize()
            password = request.POST.get('password', '')
            tipo_usuario = request.POST.get('tipo_usuario', 'responsavel') 
            paises_responsavel = request.POST.getlist('paises_responsavel')

            if not username or not password:
                return redirect('criar_usuario')

            if User.objects.filter(username=username).exists():
                return redirect('criar_usuario')

            # Criar o usuário
            user = User.objects.create_user(username=username, password=password)
            
            # Mapeamento de grupos
            grupos_map = {
                'responsavel': 'Técnicos responsáveis',
                'reporte': 'Técnicos de reporte',
                'semi_admin': 'Semi Admin'
            }
            nome_grupo = grupos_map.get(tipo_usuario, 'Técnicos de reporte')

            grupo, _ = Group.objects.get_or_create(name=nome_grupo)
            user.groups.add(grupo)
            
            # Adicionar permissões de países
            for pais_id in paises_responsavel:
                country = Country.objects.filter(id=pais_id).first()
                if country:
                    CountryPermission.objects.get_or_create(user=user, country=country)

            messages.success(request, f"Usuário {username} criado com sucesso!")
            return redirect('criar_usuario')
            
    except Exception as e:
        import traceback
        print(traceback.format_exc()) # Isso vai printar o erro exato no seu terminal!
        return HttpResponse(f"Erro Interno: {str(e)}", status=500)
    
# @login_required(login_url='subir_ocorrencia')
def subir_ocorrencia(request):
    has_full_permission = check_user_full_permission(request.user) if request.user.is_authenticated else False
    paises = Country.objects.all().order_by('name')
    responsaveis_por_pais = {}
    todos_responsaveis = []
    todos_equipamentos = []
    nome_responsaveis = []
    # Buscar os dois grupos
    grupo_responsaveis = Group.objects.filter(name='Técnicos responsáveis').first()

    # Prepara lista de responsáveis (usuários de QUALQUER UM dos dois grupos)
    usuarios_query = User.objects.all()
    
    # Filtra usuários que estão em pelo menos um dos grupos
    if  grupo_responsaveis:
        from django.db.models import Q
        query_filter = Q()
        if grupo_responsaveis:
            query_filter |= Q(groups=grupo_responsaveis)
        
        usuarios_com_permissao = usuarios_query.filter(query_filter).distinct().values('id', 'first_name', 'last_name', 'username')
    else:
        usuarios_com_permissao = []

    for user in usuarios_com_permissao:
        nome_completo = f"{user['first_name']} {user['last_name']}".strip()
        if not nome_completo:
            nome_completo = user['username']
        todos_responsaveis.append({'id': user['id'], 'name': nome_completo})
        nome_responsaveis.append(nome_completo)
        

    # Prepara lista de equipamentos
    todos_equipamentos = list(Device.objects.all().values('id', 'name'))

    # Mapeia responsáveis por país (usuários de qualquer um dos dois grupos)
    for pais in paises:
        responsaveis_por_pais[pais.id] = []
        
        # Filtra CountryPermission pelos usuários dos grupos
        permissoes_query = CountryPermission.objects.filter(country=pais)
        
        if grupo_responsaveis:
            from django.db.models import Q
            user_filter = Q()
            if grupo_responsaveis:
                user_filter |= Q(user__groups=grupo_responsaveis)
            
            permissoes_query = permissoes_query.filter(user_filter).distinct()
        
        for permissao in permissoes_query.select_related('user'):
            user = permissao.user
            nome_completo = f"{user.first_name} {user.last_name}".strip() or user.username
            responsaveis_por_pais[pais.id].append({'id': user.id, 'name': nome_completo})

    if request.method == 'POST':
        try:
            # Validações obrigatórias
            required_fields = {
                'country': 'País',
                'device': 'Equipamento',
                'technical': 'Técnico',
                'serial': 'Serial',
                'brand': 'Marca',
                'model': 'Modelo',
                'year': 'Ano',
                'version': 'Versão',
                'problem_detected': 'Problema Detectado'
            }

            missing_fields = [field_name for field_name, field_label in required_fields.items() 
                             if not request.POST.get(field_name)]
            if missing_fields:
                return JsonResponse({
                    "status": "error",
                    "message": f"Campos obrigatórios faltando: {', '.join([required_fields[f] for f in missing_fields])}"
                }, status=400)

            country = get_object_or_404(Country, id=request.POST.get("country"))
            device = get_object_or_404(Device, id=request.POST.get("device"))

            # Validação específica do ticket

            # ----------------------------------------------------------------------------------
            # VALIDAÇÃO THINKCAR: O serial DEVE obedecer ao padrão regex fornecido.
            # ----------------------------------------------------------------------------------
            serial_input = request.POST.get("serial", "").strip().upper()
            device_name = device.name.upper() # Obtém o nome do equipamento selecionado
            
            # Padrão regex para Thinkcar: 12 dígitos OU "9TDP" seguido de 8 caracteres alfanuméricos
            THINKCAR_REGEX = r"^(?:\d{12}|9TDP[A-Z0-9]{8})$"
            
            if "THINKCAR" in device_name or "READER" in device_name:
                import re
                if not re.match(THINKCAR_REGEX, serial_input):
                    return JsonResponse({
                        "status": "error",
                        "message": "Serial inválido para equipamento Thinkcar. O serial deve ter 12 dígitos ou começar com '9TDP' seguido de 8 caracteres alfanuméricos."
                    }, status=400)
            # ----------------------------------------------------------------------------------
            ticket = request.POST.get("ticket", "").strip()
            if ticket:
                if len(ticket) > 20:
                    return JsonResponse({
                        "status": "error",
                        "message": "Ticket deve ter no máximo 20 caracteres."
                    }, status=400)
                
                if Record.objects.filter(codigo_externo=ticket).exists():
                    return JsonResponse({
                        "status": "error",
                        "message": "Este ticket já está em uso. Insira um código único."
                    }, status=400)

            # Prepara dados do registro
            record_data = {
                'technical': request.POST.get("technical"),
                'responsible': request.POST.get("responsible"),
                'device': device,
                'area': request.POST.get("area_radio"),
                'serial': request.POST.get("serial"),
                'vin': request.POST.get("vin"),
                'brand': request.POST.get("brand"),
                'model': request.POST.get("model"),
                'contact': request.POST.get("contact"),
                'year': request.POST.get("year"),
                'country': country,
                'version': request.POST.get("version"),
                'tipo_chave': request.POST.get("tipo_chave"),
                'problem_detected': request.POST.get("problem_detected"),
                'tipo_ecu': request.POST.get("tipo_ecu"),
                'tipo_motor': request.POST.get("tipo_motor"),
                'sistema': None,
                'tipo_problema': None,
                'status': Record.STATUS_OCORRENCIA.REQUESTED
            }

            # Trata campos Sistema e Tipo de Problema conforme a área
            selected_area = request.POST.get("area_radio")
            if selected_area in ["IMMO", "Diagnosis", "BOX360"]:
                sistema_val = (request.POST.get("sistema") or "").strip()
                tipo_prob_val = (request.POST.get("tipo_problema") or "").strip()

                # ✅ segurança: anônimo não pode mandar "Outro..."
                if (not request.user.is_authenticated) and (sistema_val == "Outro..." or tipo_prob_val == "Outro..."):
                    return JsonResponse({
                        "status": "error",
                        "message": "Você precisa estar logado para cadastrar 'Outro' em Sistema/Tipo de Problema."
                    }, status=403)
                sistema_val = (request.POST.get("sistema") or "").strip()
                sistema_outro = (request.POST.get("sistema_outro") or "").strip()
                if sistema_val == "Outro..." and sistema_outro:
                    record_data['sistema'] = sistema_outro
                    # Tenta criar o sistema novo já
                    add_option_internal(request, 'SISTEMA', selected_area, sistema_outro)
                else:
                    record_data['sistema'] = sistema_val or None

                tipo_prob_val = (request.POST.get("tipo_problema") or "").strip()
                tipo_prob_outro = (request.POST.get("tipo_problema_outro") or "").strip()
                if tipo_prob_val == "Outro..." and tipo_prob_outro:
                    record_data['tipo_problema'] = tipo_prob_outro
                    # Tenta criar o problema novo ligado ao sistema atual (que pode ser o novo criado acima)
                    current_sys = record_data['sistema']
                    if current_sys:
                         add_option_internal(request, 'PROBLEMA', selected_area, tipo_prob_outro, system_label=current_sys)
                else:
                    record_data['tipo_problema'] = tipo_prob_val or None

            if ticket:
                record_data['codigo_externo'] = ticket

            # Validação de status
            status_input = request.POST.get("status", "Requisitado")
            status_mapping = {
                'Requisitado': Record.STATUS_OCORRENCIA.REQUESTED,
                'Concluído': Record.STATUS_OCORRENCIA.DONE,
                'Em progresso': Record.STATUS_OCORRENCIA.PROGRESS,
                'Atrasado': Record.STATUS_OCORRENCIA.LATE,
                'Aguardando China': Record.STATUS_OCORRENCIA.AWAITING_CHINA,
            }
            if status_input in status_mapping:
                record_data['status'] = status_mapping[status_input]

            # Validação de deadline
            if request.POST.get("deadline"):
                try:
                    record_data['deadline'] = datetime.strptime(
                        request.POST.get("deadline"), 
                        '%d/%m/%Y'
                    ).date()
                except ValueError:
                    return JsonResponse({
                        "status": "error",
                        "message": "Formato de data inválido. Use DD/MM/AAAA."
                    }, status=400)

            # Cria o registro
            technical = request.POST.get("technical").capitalize()
            print(technical)

            # Extrai apenas os nomes da lista de dicionários
            nomes_responsaveis_pais = [r['name'] for r in responsaveis_por_pais[pais.id]]
            if not has_full_permission:
                if technical in nome_responsaveis and technical in nomes_responsaveis_pais:
                    record_data['responsible'] = request.POST.get("technical").capitalize()
            try:
                record = Record.objects.create(**record_data)
                # LOG: criada
                create_movement_log(
                    record=record,
                    user=request.user if request.user.is_authenticated else None,
                    event_type=RecordStatusLog.EventType.CREATED,
                    field="created",
                    from_status=None,
                    to_status=record.status,
                    note=f"[OCORRÊNCIA] Criada com status {record.status}",
                )

                # LOG: responsável definido (se já nasce com responsible)
                if record.responsible and record.responsible.strip() and record.responsible != "Não identificado":
                    create_movement_log(
                        record=record,
                        user=request.user if request.user.is_authenticated else None,
                        event_type=RecordStatusLog.EventType.RESPONSIBLE_SET,
                        field="responsible",
                        from_status=record.status,
                        to_status=record.status,
                        note=f"[OCORRÊNCIA] Responsável definido na criação: {record.responsible}",
                    )
                    
            except IntegrityError as e:
                return JsonResponse({
                    "status": "error",
                    "message": "Erro ao criar registro. Verifique os dados."
                }, status=400)

            # Processa arquivos anexados
            for file in request.FILES.getlist("arquivo"):
                ArquivoOcorrencia.objects.create(
                    record=record,
                    arquivo=file,
                    nome_original=file.name
                )

            return JsonResponse({
                "status": "success",
                "message": "Ocorrência registrada com sucesso!",
                "record_id": record.id
            }, status=201)

        except Country.DoesNotExist:
            return JsonResponse({
                "status": "error",
                "message": "País selecionado não existe."
            }, status=400)
        except Device.DoesNotExist:
            return JsonResponse({
                "status": "error", 
                "message": "Equipamento selecionado não existe."
            }, status=400)
        except Exception as e:
            return JsonResponse({
                "status": "error",
                "message": f"Erro interno: {str(e)}"
            }, status=500)

    # GET request - prepara dados para o template
    paises_dict = {str(p.id): p.name for p in paises}

    # se for GET normal (primeiro carregamento)
    context = {
        'paises': paises,
        'paises_json': json.dumps(paises_dict),
        'has_full_permission': has_full_permission,
        'responsaveis_por_pais': json.dumps(responsaveis_por_pais),
        'todos_responsaveis': json.dumps(todos_responsaveis),
        'todos_equipamentos_raw': todos_equipamentos,
        'allow_outro_options': request.user.is_authenticated,
    }

    # só envia username se o usuário estiver autenticado E ainda não houver um POST que o altere
    if request.method == 'GET' and request.user.is_authenticated:
        context['username'] = request.user.username

    return render(request, 'ocorrencia/subir_ocorrencia.html', context)
# Views auxiliares para AJAX (opcionais)
def get_responsaveis_por_pais(request):
    """
    View para retornar responsáveis filtrados por país via AJAX
    """
    country_id = request.GET.get('country_id')
    
    if country_id:
        try:
            country = Country.objects.get(id=country_id)
            # Buscar responsáveis que têm permissão neste país
            permissoes = CountryPermission.objects.filter(country=country).select_related('user')
            
            responsaveis_list = []
            for permissao in permissoes:
                user = permissao.user
                nome_completo = f"{user.first_name} {user.last_name}".strip()
                if not nome_completo:
                    nome_completo = user.username
                
                responsaveis_list.append({
                    'id': user.id,
                    'name': nome_completo
                })
        except Country.DoesNotExist:
            responsaveis_list = []
    else:
        # Retornar todos os responsáveis
        usuarios_com_permissao = User.objects.filter(
            country_permissions__isnull=False
        ).distinct().values('id', 'first_name', 'last_name', 'username')
        
        responsaveis_list = []
        for user in usuarios_com_permissao:
            nome_completo = f"{user['first_name']} {user['last_name']}".strip()
            if not nome_completo:
                nome_completo = user['username']
            
            responsaveis_list.append({
                'id': user['id'],
                'name': nome_completo
            })
    
    return JsonResponse({'responsaveis': responsaveis_list})


def get_paises_por_responsavel(request):
    """
    View para retornar países filtrados por responsável via AJAX
    """
    responsavel_id = request.GET.get('responsavel_id')
    
    if responsavel_id:
        try:
            user = User.objects.get(id=responsavel_id)
            # Buscar países para os quais este usuário tem permissão
            permissoes = CountryPermission.objects.filter(user=user).select_related('country')
            
            paises_list = []
            for permissao in permissoes:
                paises_list.append({
                    'id': permissao.country.id,
                    'name': permissao.country.name
                })
        except User.DoesNotExist:
            paises_list = []
    else:
        # Retornar todos os países
        paises_list = list(Country.objects.all().values('id', 'name'))
    
    return JsonResponse({'paises': paises_list})

# Em seu arquivo views.py

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def alterar_dados(request):
    # Bloqueia edição para usuários de leitura (reporte/concluído)
    if not check_user_full_permission(request.user) and not request.user.groups.filter(name='Técnicos responsáveis').exists():
            return JsonResponse({'status': 'error', 'message': 'Permissão negada.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Método inválido'}, status=405)

    try:
        # Lógica para upload de arquivos (multipart/form-data)
        if request.content_type.startswith('multipart/form-data'):
            # ... (sua lógica de upload de arquivos permanece a mesma, não precisa mudar)
            body = request.POST
            files = request.FILES.getlist("arquivo")

            if body.get("action") == "deletar":
                file_id = body.get("file")
                try:
                    arquivo = ArquivoOcorrencia.objects.get(id=file_id)
                    arquivo.delete()
                    return JsonResponse({'status': 'success'})
                except ArquivoOcorrencia.DoesNotExist:
                    return JsonResponse({'status': 'error', 'message': 'Arquivo não encontrado'}, status=404)

            elif files:
                try:
                    record = Record.objects.get(id=body.get('record'))
                    
                    for file in files:
                        ArquivoOcorrencia.objects.create(
                            record=record,
                            arquivo=file,
                            nome_original=file.name
                        )
                    return JsonResponse({'status': 'success', 'page_num': body.get("page_num")})
                except Exception as e:
                    return JsonResponse({'status': 'error','message': f'Erro ao salvar arquivos: {str(e)}'}, status=500)
            
            # Se não for nenhuma das ações acima, retorna erro.
            return JsonResponse({'status': 'error', 'message': 'Ação multipart inválida'}, status=400)

        # Lógica para JSON puro (atualização de campos)
        # Lógica para JSON (atualização de campos)
        else:
            data = json.loads(request.body.decode('utf-8'))
            record = get_object_or_404(Record, id=data.get('id'))
            old_status = record.status
            old_finished = record.finished
            old_deadline = record.deadline
            old_responsible = record.responsible
            field_name = data.get("field")
            new_value = data.get('value')

            # Blindagem: nunca grava o placeholder "OUTRO" no banco
            if field_name == 'parceiro':
                nv = str(new_value or '').strip()
                if nv.upper() in ['OUTRO', 'OUTRO.']:
                    new_value = ''
            new_display = str(new_value)
            if field_name == 'finished' and not new_value:
                record.clear_finished_date()  # Usa o método especial
                new_display = ''
            elif field_name == 'deadline' and not new_value:
                record.clear_deadline_date()  # Usa o método especial
                new_display = ''
                
            elif field_name == 'country':
                if new_value == 'revert':
                    original_country_name = record.country_original
                    record.country = Country.objects.filter(name=original_country_name).first()
                    new_display = original_country_name or ''
                else:
                    country_obj = get_object_or_404(Country, id=new_value)
                    record.country = country_obj
                    new_display = country_obj.name
            
            elif field_name in DATE_COLUMNS and new_value:
                parsed_date = datetime.strptime(new_value, '%d/%m/%Y').date()
                setattr(record, field_name, parsed_date)
                new_display = parsed_date.strftime('%Y-%m-%d')
            
            # 👇 BLOCO NOVO: Cria a mensagem no chat quando a Solução for preenchida 👇
            elif field_name == 'solution':
                setattr(record, field_name, new_value)
                new_display = new_value
                
                # Cria a mensagem no banco de dados do Chat
                msg = ChatMessage.objects.create(
                    record=record,
                    author=request.user,
                    message=f"Solução: {new_value}"
                )
                
                # Dispara a mensagem instantaneamente no WebSocket para quem estiver com o Popup aberto
                try:
                    from channels.layers import get_channel_layer
                    from asgiref.sync import async_to_sync
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        f"chat_{record.id}",
                        {
                            "type": "chat_message",
                            "payload": {
                                "action": "new_message",
                                "id": msg.id,
                                "message": msg.message,
                                "author": request.user.username,
                                "timestamp": msg.timestamp.isoformat(),
                                "image_url": "",
                                "image_name": "",
                                "is_edited": False
                            }
                        }
                    )
                except Exception as e:
                    print(f"Aviso: Não foi possível transmitir a solução no WebSocket em tempo real. Erro: {e}")
            # 👆 FIM DO BLOCO NOVO 👆
            
            else:
                setattr(record, field_name, new_value)
                new_display = new_value

            # SALVA O REGISTRO UMA ÚNICA VEZ.
            record.save()
            new_status = record.status

            # 1) Responsible
            if old_responsible != record.responsible:
                msg = f"[OCORRÊNCIA] Responsável: {old_responsible or '-'} -> {record.responsible or '-'}"
                create_movement_log(
                    record=record,
                    user=request.user,
                    event_type=RecordStatusLog.EventType.RESPONSIBLE_SET,
                    field="responsible",
                    from_status=old_status,
                    to_status=new_status,
                    note=msg,
                )
                add_admin_log(request.user, record, msg)

            # 2) Deadline
            if old_deadline != record.deadline:
                msg = f"[OCORRÊNCIA] Deadline: {old_deadline or '-'} -> {record.deadline or '-'}"
                create_movement_log(
                    record=record,
                    user=request.user,
                    event_type=RecordStatusLog.EventType.DEADLINE,
                    field="deadline",
                    from_status=old_status,
                    to_status=new_status,
                    note=msg,
                )
                add_admin_log(request.user, record, msg)

            # 3) Finished
            if old_finished != record.finished:
                msg = f"[OCORRÊNCIA] Finished: {old_finished or '-'} -> {record.finished or '-'}"
                create_movement_log(
                    record=record,
                    user=request.user,
                    event_type=RecordStatusLog.EventType.FINISHED,
                    field="finished",
                    from_status=old_status,
                    to_status=new_status,
                    note=msg,
                )
                add_admin_log(request.user, record, msg)

            # 4) Status (sempre por último, pra pegar status final após clean())
            if old_status != new_status:
                msg = f"[OCORRÊNCIA] Status: {old_status} -> {new_status} (campo: {field_name})"
                create_movement_log(
                    record=record,
                    user=request.user,
                    event_type=RecordStatusLog.EventType.STATUS,
                    field="status",
                    from_status=old_status,
                    to_status=new_status,
                    note=msg,
                )
                add_admin_log(request.user, record, msg)

            if field_name == 'feedback_manager' and new_value and str(new_value).strip():
                criar_notificacao_feedback(record, 'feedback_manager', request.user)
            
            return JsonResponse({
                'status': 'success',
                'new_display': new_display,
                'page_num': data.get("page_num")
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

# Alias para compatibilidade
update_record_view = alterar_dados


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def download_arquivo(request, arquivo_id):
    """
    Download seguro de arquivo anexado (compatível com MinIO/S3 via django-storages).
    """
    arquivo = get_object_or_404(ArquivoOcorrencia, id=arquivo_id)
    record = arquivo.record
    user = request.user

    # Permissões
    if user.groups.filter(name='Somente Concluído').exists() or user.groups.filter(name='Técnicos de reporte').exists():
        if record.status != Record.STATUS_OCORRENCIA.DONE:
            raise Http404("Arquivo não encontrado ou sem permissão")
        # ✅ agora filtra por país também
        if record.country and not CountryPermission.objects.filter(user=user, country=record.country).exists():
            raise Http404("Arquivo não encontrado ou sem permissão")
    elif not check_user_full_permission(user):
        # Se tiver country, valida permissão por país
        if record.country and not CountryPermission.objects.filter(user=user, country=record.country).exists():
            raise Http404("Arquivo não encontrado ou sem permissão")

    if not arquivo.arquivo:
        raise Http404("Arquivo não encontrado")

    filename = arquivo.nome_original or os.path.basename(arquivo.arquivo.name)

    try:
        file_handle = arquivo.arquivo.open("rb")  # MinIO/S3: abre via storage
    except Exception as e:
        print(f"Erro abrindo arquivo {arquivo_id} no storage: {e}")
        raise Http404("Arquivo não encontrado")

    response = FileResponse(file_handle, as_attachment=True, filename=filename)

    content_type, _ = mimetypes.guess_type(filename)
    if content_type:
        response["Content-Type"] = content_type

    return response



def get_record(request, pk):
    try:
        record = Record.objects.prefetch_related('arquivos').get(id=pk)
        # Restringe visualização para usuários de leitura (reporte/concluído)
        if request.user.is_authenticated and (request.user.groups.filter(name='Somente Concluído').exists() or request.user.groups.filter(name='Técnicos de reporte').exists()):
            if record.status != Record.STATUS_OCORRENCIA.DONE:
                return JsonResponse({'error': 'Registro não encontrado'}, status=404)
        # Solução registrada no banco (preferencial)
        last_solution = getattr(record, 'solution', None)
        if request.user.is_authenticated and (
            request.user.groups.filter(name='Somente Concluído').exists() or
            request.user.groups.filter(name='Técnicos de reporte').exists()
        ):
            if record.status != Record.STATUS_OCORRENCIA.DONE:
                return JsonResponse({'error': 'Registro não encontrado'}, status=404)
            if record.country and not CountryPermission.objects.filter(user=request.user, country=record.country).exists():
                return JsonResponse({'error': 'Registro não encontrado'}, status=404)
        

        try:
            if not last_solution:
                # Fallback: scan do chat e, se encontrar, salva em record.solution
                sol_pattern = re.compile(r"(?i)solu[cç][aã]o\s*[:\-]\s*(.+)")
                for msg in ChatMessage.objects.filter(record=record).order_by('-timestamp')[:200]:
                    raw = (msg.message or '').strip()
                    m = sol_pattern.search(raw)
                    if m:
                        last_solution = m.group(1).strip()
                        try:
                            record.solution = last_solution
                            record.save(update_fields=['solution'])
                        except Exception:
                            pass
                        break
        except Exception:
            last_solution = None

        data = {
            "id": record.id,
            "origem_ocorrencia": record.origem_ocorrencia or "",
            "parceiro": record.parceiro or "",
            "codigo_externo": record.codigo_externo or str(record.id),
            "technical": record.technical,
            "responsible": record.responsible,
            "device": str(record.device) if record.device else None,
            "ticket_fabricante": record.ticket_fabricante or "",
            "area": record.area,
            "serial": record.serial,
            'tipo_ecu': record.tipo_ecu,
            'tipo_motor': record.tipo_motor,
            "vin": record.vin,
            "brand": record.brand,
            "model": record.model,
            "contact": record.contact,
            "year": record.year,
            "version": record.version,
            "tipo_chave": record.tipo_chave,
            "detalhes_responsavel": record.detalhes_responsavel,
            "sistema": record.sistema,
            "tipo_problema": record.tipo_problema,
            "country": record.country.name if record.country else None,
            "status": record.status,
            "data": record.data.strftime("%Y-%m-%d") if record.data else None,
            "deadline": record.deadline.strftime("%Y-%m-%d") if record.deadline else None,
            "finished": record.finished.strftime("%Y-%m-%d") if record.finished else None,
            "problem_detected": record.problem_detected,
            "feedback_technical": record.feedback_technical,
            "feedback_manager": record.feedback_manager,
            "solution": last_solution,
            "arquivos": [
                {
                    "id": arquivo.id,
                    "nome_original": arquivo.nome_original,
                    "caminho": arquivo.arquivo.url if arquivo.arquivo else None,
                    "data_upload": arquivo.data_upload.strftime("%d/%m/%Y %H:%M")
                }
                for arquivo in record.arquivos.all()
            ]
        }

        return JsonResponse(data)

    except Record.DoesNotExist:
        return JsonResponse({'error': 'Registro não encontrado'}, status=404)


def options_config(request):
    """Retorna opções configuráveis.
    - SISTEMA por área
    - PROBLEMA por sistema (quando parent definido) e fallback por área
    Estrutura:
    {
      "SISTEMA": {"IMMO": [...], "Diagnosis": [...], "Device": [...]},
      "PROBLEMA_BY_SYSTEM": {"Injeção Eletrônica": [...], ...},
      "PROBLEMA_BY_AREA": {"IMMO": [...], "Diagnosis": [...], "Device": [...]}
    }
    """
    qs = OptionItem.objects.filter(active=True).order_by('category', 'area', 'parent__label', 'order', 'label')

    # Usa sets internamente para evitar duplicados
    sist = { 'IMMO': set(), 'Diagnosis': set(), 'Device': set(), 'BOX360': set() }
    prob_by_sys = {}            # key: system label -> set()
    # Para calcular fallback de área, vamos armazenar os conjuntos por SISTEMA (para fazer interseção)
    area_systems = { 'IMMO': set(), 'Diagnosis': set(), 'Device': set(), 'BOX360': set() }  # nomes dos sistemas por área
    probs_per_system = {}  # key: system label -> set()

    for item in qs:
        if item.category == 'SISTEMA':
            sist.setdefault(item.area, set()).add(item.label)
        else:  # PROBLEMA
            if item.parent and item.parent.label:
                key = item.parent.label
                prob_by_sys.setdefault(key, set()).add(item.label)
                probs_per_system.setdefault(key, set()).add(item.label)
                # registra sistema -> área
                # Precisamos ligar system label à sua área (buscaremos pela OptionItem de sistema abaixo se necessário)
            else:
                # Problema "global" (sem parent) — entra em todos os sistemas da área no fallback
                # Guardaremos em um marcador especial por área usando um nome fictício de sistema "__GLOBAL__<AREA>"
                key = f"__GLOBAL__{item.area}__"
                prob_by_sys.setdefault(key, set()).add(item.label)
                probs_per_system.setdefault(key, set()).add(item.label)
            # Nota: o fallback por área será calculado por interseção entre sistemas + globais

    def sorted_unique(values):
        # deduplica e remove vazio
        return sorted({x for x in values if x and x != 'Outro...'}, key=lambda s: s.lower())

    # Constrói o mapa área -> [sets de problemas por sistema dessa área]
    # 1) Obter sistemas por área a partir de OptionItem (category=SISTEMA)
    sistemas_qs = OptionItem.objects.filter(category='SISTEMA', active=True)
    system_area = {}
    for s in sistemas_qs:
        sist.setdefault(s.area, set()).add(s.label)
        area_systems.setdefault(s.area, set()).add(s.label)
        system_area[s.label] = s.area

    # 2) Calcular fallback por área: interseção dos problemas de todos os sistemas da área
    problema_by_area_final = {}
    for area, systems in area_systems.items():
        sets = []
        # problemas "globais" sem parent contam para todas as áreas respectivas
        global_key = f"__GLOBAL__{area}__"
        if global_key in probs_per_system:
            sets.append(probs_per_system[global_key])
        for sys_label in systems:
            if sys_label in probs_per_system:
                sets.append(probs_per_system[sys_label])
        if not sets:
            problema_by_area_final[area] = sorted_unique([])
        else:
            inter = set.intersection(*sets) if len(sets) > 1 else set(sets[0])
            problema_by_area_final[area] = sorted_unique(inter)

    result = {
        'SISTEMA': { area: sorted(list(vals), key=lambda s: s.lower()) for area, vals in sist.items() },
        'PROBLEMA_BY_SYSTEM': { sys: sorted_unique(vals) for sys, vals in prob_by_sys.items() if not sys.startswith('__GLOBAL__') },
        'PROBLEMA_BY_AREA': problema_by_area_final,
    }

    return JsonResponse(result)
    
def add_option_internal(request, category, area, label, system_label=None):
    """Helper interno para criar opções automaticamente ao submeter 'Outro...'."""
    if not label or not area: return
    
    defaults_common = {'order': 0, 'active': True, 'cod_usuario': request.user if request.user.is_authenticated else None}
    
    if category == 'SISTEMA':
        sys_obj, created = OptionItem.objects.get_or_create(
            area=area, category='SISTEMA', label=label, defaults=defaults_common
        )
        if created:
             # Seed default problems
             defaults_list = DEFAULT_PROBLEMS_BY_AREA.get(area, [])
             for idx, prob_label in enumerate(defaults_list):
                 OptionItem.objects.get_or_create(area=area, category='PROBLEMA', label=prob_label, parent=sys_obj, defaults={'order': idx, 'active': True})
                 
    elif category == 'PROBLEMA':
        if system_label:
            try:
                parent = OptionItem.objects.get(area=area, category='SISTEMA', label=system_label)
                OptionItem.objects.get_or_create(
                    area=area, category='PROBLEMA', label=label, parent=parent, defaults=defaults_common
                )
            except OptionItem.DoesNotExist:
                pass


@require_http_methods(["POST"])
def add_option_item(request):
    """Cria opções dinamicamente a partir do frontend.
    Body JSON:
      category: 'SISTEMA' | 'PROBLEMA'
      area: 'IMMO' | 'Diagnosis' | 'Device'
      label: texto
      system_label: (opcional) rótulo do sistema para vincular o problema
      global_problem: (opcional bool) quando verdadeiro, cria o problema para TODOS os sistemas da área
    Retorna {status:'success', created:n}
    """
    try:
        data = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'status': 'error', 'message': 'JSON inválido.'}, status=400)

    category = (data.get('category') or '').strip().upper()
    area = (data.get('area') or '').strip()
    label = (data.get('label') or '').strip()
    system_label = (data.get('system_label') or '').strip()
    global_problem = bool(data.get('global_problem'))

    if category not in ('SISTEMA', 'PROBLEMA'):
        return JsonResponse({'status': 'error', 'message': 'Categoria inválida.'}, status=400)
    if not area or not label:
        return JsonResponse({'status': 'error', 'message': 'Área e label são obrigatórios.'}, status=400)

    created = 0
    try:
        if category == 'SISTEMA':
            sys_obj, was_created = OptionItem.objects.get_or_create(
                area=area,
                category='SISTEMA',
                label=label,
                defaults={'order': 0, 'active': True, 'cod_usuario': request.user if request.user.is_authenticated else None}
            )
            created += int(was_created)

            # Ao criar (ou quando ainda não há problemas vinculados), semear problemas padrão da área
            try:
                should_seed = was_created or not OptionItem.objects.filter(
                    area=area, category='PROBLEMA', parent=sys_obj
                ).exists()
                if should_seed:
                    defaults_list = DEFAULT_PROBLEMS_BY_AREA.get(area, [])
                    for idx, prob_label in enumerate(defaults_list):
                        _, was_p_created = OptionItem.objects.get_or_create(
                            area=area,
                            category='PROBLEMA',
                            label=prob_label,
                            parent=sys_obj,
                            defaults={'order': idx, 'active': True}
                        )
                        created += int(was_p_created)
            except Exception:
                # Não falha a requisição caso a semeadura automática dê erro
                pass
        else:
            # PROBLEMA
            if global_problem:
                # Cria problema GLOBAL (sem parent) para TODOS os sistemas da área?
                # Na verdade, a lógica atual do `options_config` suporta problema "global" definido como
                # parent=None. Então basta criar UM OptionItem c/ parent=None nesta área.
                prob_obj, was_created = OptionItem.objects.get_or_create(
                    area=area,
                    category='PROBLEMA',
                    label=label,
                    parent=None,
                    defaults={'order': 0, 'active': True, 'cod_usuario': request.user if request.user.is_authenticated else None}
                )
                created += int(was_created)
            else:
                # Problema vinculado a um sistema específico
                if not system_label:
                    return JsonResponse({'status': 'error', 'message': 'System label obrigatório para problema não-global.'}, status=400)
                
                # Busca sistema pai
                try:
                    parent_sys = OptionItem.objects.get(area=area, category='SISTEMA', label=system_label)
                except OptionItem.DoesNotExist:
                    # Se não existe o sistema, podemos criar ou dar erro.
                    # Aqui vamos dar erro pois deveria ter sido criado antes ou selecionado.
                    return JsonResponse({'status': 'error', 'message': f'Sistema "{system_label}" não encontrado.'}, status=400)

                prob_obj, was_created = OptionItem.objects.get_or_create(
                    area=area,
                    category='PROBLEMA',
                    label=label,
                    parent=parent_sys,
                    defaults={'order': 0, 'active': True, 'cod_usuario': request.user if request.user.is_authenticated else None}
                )
                created += int(was_created)

        return JsonResponse({'status': 'success', 'created': created})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


def criar_notificacao_feedback(record, tipo_feedback, gestor_user):
    """
    Cria uma notificação quando um gestor adiciona feedback a uma ocorrência
    """
    try:
        # Buscar o usuário responsável pela ocorrência
        if record.responsible and record.responsible != "Não identificado":
            # Tentar encontrar o usuário pelo nome completo ou username
            usuarios_responsaveis = User.objects.filter(
                Q(first_name__icontains=record.responsible.split()[0]) |
                Q(username__icontains=record.responsible) |
                Q(last_name__icontains=record.responsible.split()[-1] if len(record.responsible.split()) > 1 else record.responsible)
            )
            
            for usuario in usuarios_responsaveis:
                # Evitar criar notificação para o próprio gestor que fez o feedback
                if usuario.id != gestor_user.id:
                    # Verificar se já existe uma notificação não lida para esta ocorrência e usuário
                    notificacao_existente = Notificacao.objects.filter(
                        user=usuario,
                        record=record,
                        tipo=tipo_feedback,
                        lida=False
                    ).first()
                    
                    if not notificacao_existente:
                        # Criar nova notificação
                        titulo = f"Nova mensagem na ocorrência #{record.codigo_externo or record.id}"
                        resumo = f"{record.responsible} mandou uma nova mensagem"
                        
                        Notificacao.objects.create(
                            user=usuario,
                            record=record,
                            tipo=tipo_feedback,
                            titulo=titulo,
                            resumo=resumo
                        )
    except Exception as e:
        print(f"Erro ao criar notificação: {e}")

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def listar_notificacoes(request):
    """
    API para listar notificações não lidas do usuário logado
    """
    try:
        notificacoes = Notificacao.objects.filter(
            user=request.user,
            lida=False
        ).select_related('record', 'record__device').order_by('-criada_em')
        
        notificacoes_data = []
        for notificacao in notificacoes:
            notificacoes_data.append({
                'id': notificacao.id,
                'titulo': notificacao.titulo,
                'resumo': notificacao.resumo,
                'tipo': notificacao.tipo,
                'criada_em': notificacao.criada_em.strftime('%d/%m/%Y %H:%M'),
                'record_id': notificacao.record.id,
                'record_codigo': notificacao.record.codigo_externo or str(notificacao.record.id)
            })
        
        return JsonResponse({
            'status': 'success',
            'notificacoes': notificacoes_data,
            'total': len(notificacoes_data)
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def marcar_notificacao_lida(request, notificacao_id):
    """
    API para marcar uma notificação como lida
    """
    try:
        notificacao = get_object_or_404(Notificacao, id=notificacao_id, user=request.user)
        notificacao.marcar_como_lida()
        
        return JsonResponse({'status': 'success', 'message': 'Notificação marcada como lida'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def marcar_notificacoes_por_record_como_lidas(request, record_id):
    """
    API para marcar todas as notificações não lidas de um record como lidas
    """
    try:
        notificacoes = Notificacao.objects.filter(
            user =request.user,
            record_id=record_id,
        )
        count = notificacoes.count()
        for notificacao in notificacoes :
            notificacao.marcar_como_lida()
        
        return JsonResponse({
            'status': 'success', 
            'message': f'{count} notificação(s) marcada(s) como lida(s)',
            'count': count
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

def contar_notificacoes_nao_lidas(request):
    """
    API para contar notificações não lidas do usuário logado
    """
    try:
        count = Notificacao.objects.filter(user=request.user, lida=False).count()
        return JsonResponse({'status': 'success', 'count': count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

# Em seu arquivo views.py

@login_required(login_url=settings.URL_LOGIN) # Adapte 'URL_LOGIN' se necessário
@require_http_methods(["GET", "POST"])
@require_system_access("ocorrencia")
def gerar_pdf_ocorrencia(request, record_id=None):
    """
    Gera um arquivo PDF com os detalhes COMPLETOS de uma ocorrência,
    com quebra de linha automática e tradução automática para inglês.
    """
    try:
        # Controle de seções opcionais
        exclude_problem = False

        # Se a requisição for POST, pega o ID do corpo da requisição
        if request.method == 'POST':
            data = json.loads(request.body.decode('utf-8')) if request.body else {}

            override_device = data.get('override_device')
            override_serial = data.get('override_serial')

            record_id = data.get('record_id')
            

            # Permite inibir seção "Problem Detected" quando acionado pelo campo do responsável
            exclude_problem = bool(data.get('exclude_problem') or data.get('only_responsible') or False)
            if not record_id:
                return JsonResponse({'status': 'error', 'message': 'ID da ocorrência não fornecido.'}, status=400)
        else:
            # Também aceita via querystring para GET
            exclude_problem = (request.GET.get('exclude_problem') in ['1', 'true', 'True']) or (
                request.GET.get('only_responsible') in ['1', 'true', 'True']
            )

        # Busca a ocorrência no banco de dados ou retorna um erro 404
        record = get_object_or_404(Record, id=record_id)
        device_name = override_device or record.device.name
        serial = override_serial or record.serial
        # Se for usuário de leitura (reporte/concluído), só permite gerar PDF para concluídas
        if request.user.groups.filter(name='Somente Concluído').exists() or request.user.groups.filter(name='Técnicos de reporte').exists():
            if record.status != Record.STATUS_OCORRENCIA.DONE:
                return JsonResponse({'status': 'error', 'message': 'Permissão negada.'}, status=403)

        # Cria um buffer de bytes em memória para o arquivo PDF
        buffer = io.BytesIO()

        # Cria o objeto PDF (canvas), usando o buffer como seu "arquivo"
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter  # Tamanho da página (8.5 x 11 polegadas)

        # --- ESTILOS PARA OS PARÁGRAFOS ---
        styles = getSampleStyleSheet()
        style_body = styles['BodyText']
        style_label = ParagraphStyle(name='Label', parent=style_body, fontName='Helvetica-Bold')

        # --- FUNÇÕES AUXILIARES INTERNAS ---
        def draw_field(x, y, label, value):
            """Desenha um par de 'Rótulo: Valor' com alinhamento dinâmico."""
            p.setFont("Helvetica-Bold", 11)
            label_text = f"{label}:"
            p.drawString(x, y, label_text)
            
            label_width = p.stringWidth(label_text, "Helvetica-Bold", 11)
            value_x_position = x + label_width + 10  # 10 pontos de espaçamento
            
            p.setFont("Helvetica", 11)
            p.drawString(value_x_position, y, str(value or "N/A"))
            
            return y - (0.25 * inch) # Retorna a próxima posição Y

        def draw_long_text_paragraph(x, y, label, text_content, translate=True):
            """Desenha um rótulo e um parágrafo de texto longo com quebra de linha automática."""
            p.setFont("Helvetica-Bold", 12)
            p.drawString(x, y, f"{label}:")
            y -= 0.25 * inch

            if translate:
                translated_text = traduzir_texto(text_content)
            else:
                translated_text = text_content

            if translated_text and isinstance(translated_text, str) and translated_text.strip() and translated_text != "N/A":
                prepared_text = translated_text.replace('\n', '<br/>')
            else:
                prepared_text = "No content provided."

            paragraph = Paragraph(prepared_text, style_body)
            
            available_width = width - (2 * x)
            w, h = paragraph.wrap(available_width, height)
            
            if y - h < 0.75 * inch: # Margem de segurança inferior
                p.showPage()
                y = height - 1 * inch # Reinicia no topo da nova página

            paragraph.drawOn(p, x, y - h)
            return y - h - 0.5 * inch # Retorna a posição Y final

        # ==================================================================
        # INÍCIO DO DESENHO DO CONTEÚDO DO PDF
        # ==================================================================
        
        # --- Title ---
        p.setFont("Helvetica-Bold", 18)
        p.drawCentredString(width / 2.0, height - 0.75 * inch, "Occurrence Report")
        p.setFont("Helvetica", 12)
        p.drawCentredString(width / 2.0, height - 1.0 * inch, f"Occurrence ID: {record.codigo_externo or record.id}")

        # Pre-traduz os campos em lote para máxima eficiência e confiabilidade
        batch_fields = [
            record.country.name if record.country else "N/A",
            record.area or "N/A",
            record.problem_detected or "N/A",
            record.detalhes_responsavel or "N/A",
            record.solution or "N/A"
        ]
        translated_batch = traduzir_texto(batch_fields)
        
        country_en = translated_batch[0]
        area_en = translated_batch[1]
        problem_en = translated_batch[2]
        resp_details_en = translated_batch[3]
        solution_en = translated_batch[4]

        # --- Seção de Informações Gerais (2 colunas) ---
        y_start = height - 1.5 * inch
        p.line(0.5 * inch, y_start + 0.1 * inch, width - 0.5 * inch, y_start + 0.1 * inch)
        
        x1 = 1 * inch
        y1 = y_start - (6 * mm)
        
        y1 = draw_field(x1, y1, "Technical", record.technical)
        y1 = draw_field(x1, y1, "Responsible", record.responsible)
        y1 = draw_field(x1, y1, "Country", country_en)
        y1 = draw_field(x1, y1, "Device", device_name)
        y1 = draw_field(x1, y1, "Area", area_en)

        # Coluna 2
        x2 = 4.5 * inch
        y2 = y_start - (6 * mm)

        y2 = draw_field(x2, y2, "Brand", record.brand)
        y2 = draw_field(x2, y2, "Model", record.model)
        y2 = draw_field(x2, y2, "Serial", serial)
        y2 = draw_field(x2, y2, "VIN", record.vin)
        y2 = draw_field(x2, y2, "Year", record.year)
        y2 = draw_field(x2, y2, "Version", record.version)

        # --- Seção de Detalhes (Textos Longos) ---
        y_next_section = min(y1, y2) - 0.3 * inch
        p.line(0.5 * inch, y_next_section + 0.1 * inch, width - 0.5 * inch, y_next_section + 0.1 * inch)
        y_text = y_next_section - 0.2 * inch
        # Problema detectado (opcional)
        if not exclude_problem:
            y_text = draw_long_text_paragraph(x1, y_text, "Problem Detected", problem_en, translate=False)
        # Detalhes do responsável
        y_text = draw_long_text_paragraph(x1, y_text, "Responsible Details", resp_details_en, translate=False)

        # Solução
        if record.solution:
            y_text = draw_long_text_paragraph(x1, y_text, "Solution", solution_en, translate=False)

        # ==================================================================
        # FINALIZAÇÃO DO ARQUIVO PDF
        # ==================================================================
        p.showPage()
        p.save()

        buffer.seek(0)
        filename = f'ocorrencia_{record.codigo_externo}_{record.serial}.pdf'
        response = FileResponse(buffer, as_attachment=True, filename=filename)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        
        return response

    except Record.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Ocorrência não encontrada.'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': 'Ocorreu um erro interno ao gerar o PDF.'}, status=500)


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def dashboard_view(request):
    context = {
        'dashboard': dashboard_responsavel(
            request.user,
            request,
            responsible=request.GET.get('responsible'),
            status=request.GET.get('status'),
            country=request.GET.get('country'),
        ),
        'responsaveis': Record.objects.values_list(
            'responsible', flat=True
        ).exclude(responsible__isnull=True).exclude(
            responsible=''
        ).distinct(),
        'status_list': Record.STATUS_OCORRENCIA.choices,
        'paises_permitidos': Country.objects.all() if request.user.is_superuser else Country.objects.filter(
            id__in=CountryPermission.objects.filter(
                user=request.user
            ).values_list("country_id", flat=True)
        ),
    }

    return render(request, 'ocorrencia/dashboard.html', context)


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def gerar_relatorio_dashboard(request):
    records = lista_detalhada(
        request.user,
        request,
        responsible=request.GET.get("responsible"),
        status=request.GET.get("status"),
        country=request.GET.get("country"),
    )

    # Tradução em lote para o relatório do dashboard (Otimizado)
    problemas_originais = [r.problem_detected for r in records]
    if problemas_originais:
        problemas_traduzidos = traduzir_texto(problemas_originais)
        # Associa as traduções de volta aos objetos (em memória)
        for i, r in enumerate(records):
            r.problem_detected_en = problemas_traduzidos[i]

    html_string = render_to_string(
        "ocorrencia/dashboard_pdf.html",
        {
            "records": records,
            "filters": {
                "status": request.GET.get("status") or "Todos",
                "responsible": request.GET.get("responsible") or "Todos",
                "country": request.GET.get("country") or "Todos",
            },
            "now": timezone.now(),
        }
    )

    pdf = HTML(
        string=html_string,
        base_url=request.build_absolute_uri("/")
    ).write_pdf()

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = "inline; filename=relatorio_ocorrencias.pdf"
    return response


@login_required(login_url=settings.URL_LOGIN)
@require_system_access("ocorrencia")
def dashboard_detalhes(request):
    records = lista_detalhada(
        request.user,
        request,
        responsible=request.GET.get("responsible"),
        status=request.GET.get("status"),
        country=request.GET.get("country"),
    )

    return render(
        request,
        "ocorrencia/dashboard_detalhes.html",
        {"records": records}
    )

@login_required(login_url=settings.URL_LOGIN)
@require_http_methods(["POST"])
@require_system_access("ocorrencia")
def clonar_ocorrencia(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        original_id = data.get('record_id')
        target_device_name = data.get('target_device')
        new_serial = data.get('new_serial')
        new_version = data.get('new_version')

        if not original_id or not target_device_name or not new_serial:
            return JsonResponse({'status': 'error', 'message': 'Dados incompletos para clonagem.'}, status=400)

        # 1. Busca o registro original
        original = get_object_or_404(Record, id=original_id)

        # 2. Busca o novo dispositivo (Device)
        # Usamos icontains para flexibilidade (ex: "EAATA90" achar "EAATA 90")
        # Mas idealmente o nome deve ser exato ou muito próximo.
        # Vamos tentar buscar exato primeiro, ou pegar o primeiro que contem o nome.
        new_device = Device.objects.filter(name__icontains=target_device_name).first()
        
        if not new_device:
            return JsonResponse({'status': 'error', 'message': f'Equipamento {target_device_name} não encontrado no banco de dados.'}, status=404)

        # 3. Clona o registro
        # Criamos um novo objeto com os dados do original, exceto ID e PK
        new_record = Record.objects.create(
            technical=original.technical,
            responsible=original.responsible,
            country=original.country,
            device=new_device,          # Novo Device
            serial=new_serial,          # Novo Serial
            
            # Copia os demais campos
            area=original.area,
            vin=original.vin,
            brand=original.brand,
            model=original.model,
            contact=original.contact,
            year=original.year,
            version=new_version,
            tipo_chave=original.tipo_chave,
            problem_detected=original.problem_detected,
            tipo_ecu=original.tipo_ecu,
            tipo_motor=original.tipo_motor,
            sistema=original.sistema,
            tipo_problema=original.tipo_problema,
            
            detalhes_responsavel=original.detalhes_responsavel,
            feedback_technical=original.feedback_technical,
            feedback_manager=original.feedback_manager,
            solution=original.solution,
            
            # Define status. Pode manter o original ou resetar. 
            # Geralmente clone mantém o status se for para gerar documentação.
            status=original.status, 
            
            # Datas
            data=timezone.now(), # Data de criação é hoje
            deadline=original.deadline,
            finished=original.finished,
            
            # Codigo externo: Deixamos None para assumir o ID ou lógica padrão, 
            # ou copiamos se fizer sentido (mas tickets devem ser únicos).
            # Vamos deixar None para que o sistema use o ID como fallback no PDF.
            codigo_externo=None 
        )

        # 4. (Opcional) Copiar arquivos? 
        # Se desejar copiar os arquivos anexados, descomente abaixo:
        # for arq in original.arquivos.all():
        #     ArquivoOcorrencia.objects.create(
        #         record=new_record,
        #         arquivo=arq.arquivo, # Isso aponta para o mesmo arquivo físico
        #         nome_original=arq.nome_original
        #     )

        return JsonResponse({
            'status': 'success', 
            'new_id': new_record.id,
            'new_codigo': new_record.codigo_externo or str(new_record.id)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
@login_required(login_url=settings.URL_LOGIN)
@require_POST
def edit_chat_message(request):
    try:
        data = json.loads(request.body.decode('utf-8'))
        msg_id = data.get('id')
        record_id = data.get('record_id')
        old_text = data.get('old_text')
        new_text = data.get('new_text')

        if not new_text:
            return JsonResponse({'status': 'error', 'message': 'A mensagem não pode ficar vazia.'}, status=400)

        # Se o WebSocket enviar o ID, achamos direto
        if msg_id:
            msg = get_object_or_404(ChatMessage, id=msg_id, author=request.user)
        else:
            # Fallback inteligente: acha a última mensagem do usuário nessa ocorrência com o texto antigo
            msg = ChatMessage.objects.filter(record_id=record_id, author=request.user, message=old_text).last()
            if not msg:
                return JsonResponse({'status': 'error', 'message': 'Mensagem original não encontrada.'}, status=404)

        msg.message = new_text
        msg.save(update_fields=['message'])
        
        return JsonResponse({'status': 'success', 'new_message': new_text})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)