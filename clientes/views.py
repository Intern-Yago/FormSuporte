from django.core.paginator import Paginator
from django.db.models import Count, Q, Prefetch, Value, IntegerField
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from painel.decorators import require_system_access

from .models import Cliente

# importa o model do suporte
from situacao_veiculo.models import Cliente as ClienteSuporte
from django.conf import settings
from .integrations.odoo_client import OdooClient, OdooConfig 
from .integrations.shopify_client import ShopifyClient
from ocorrencia_erro.models import Record
from situacao_veiculo.models import SerialSearchLog
from rest_framework.authtoken.models import Token
from simulador.models import Registro

def _can_view_all_orcamentos(user):
    if user.is_superuser: return True
    profile = getattr(user, 'profile', None)
    role = getattr(profile, 'role', None)
    setor = getattr(profile, 'setor', None)
    return bool(role in ['dono', 'diretor', 'gestor'] or setor == 'ti')

def _is_colaborador_comercial(user):
    profile = getattr(user, 'profile', None)
    role = getattr(profile, 'role', None)
    setor = getattr(profile, 'setor', None)
    return bool(role == 'colaborador' and setor == 'comercial')

def _formatar_telefone(tel):
    if not tel: return "Sem telefone"
    tel = tel.strip()
    if not tel.isdigit(): return tel
    if len(tel) == 13: return f"+{tel[:2]} ({tel[2:4]}) {tel[4:9]}-{tel[9:]}"
    elif len(tel) == 11: return f"({tel[:2]}) {tel[2:7]}-{tel[7:]}"
    elif len(tel) == 10: return f"({tel[:2]}) {tel[2:6]}-{tel[6:]}"
    elif len(tel) == 9: return f"{tel[:5]}-{tel[5:]}"
    elif len(tel) == 8: return f"{tel[:4]}-{tel[4:]}"
    return tel

def _formatar_documento(doc):
    if not doc: return "Não informado"
    doc = doc.strip()
    if not doc.isdigit(): return doc
    if len(doc) == 11: return f"{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}"
    elif len(doc) == 14: return f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}"
    return doc

def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())

def _status_label(suporte_obj):
    status = getattr(suporte_obj, "status", "") or ""
    if status in ["bloqueado", "vencido"]: return "Suporte vencido"
    if status == "vencendo": return "Suporte a vencer"
    if status == "direito": return "Suporte liberado"
    if status == "bloqueado_data_invalida": return "Dados inválidos"
    return "Indefinido"

def _status_class(suporte_obj):
    status = getattr(suporte_obj, "status", "") or ""
    if status in ["bloqueado", "vencido"]: return "status-vencido"
    if status == "vencendo": return "status-vencendo"
    if status == "direito": return "status-direito"
    return "status-indefinido"

def _can_manage_all_users(user):
    return _is_dono(user) or _is_diretor(user) or _is_gestor_ti(user) or _is_gestor_suporte(user)

def _is_dono(user):
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or getattr(profile, 'role', None) == 'dono')

def _is_diretor(user):
    profile = getattr(user, 'profile', None)
    return bool(getattr(profile, 'role', None) == 'diretor')

def _is_gestor_ti(user):
    profile = getattr(user, 'profile', None)
    return bool(getattr(profile, 'role', None) == 'gestor' and getattr(profile, 'setor', None) == 'ti')

def _is_gestor_suporte(user):
    profile = getattr(user, 'profile', None)
    return bool(getattr(profile, 'role', None) == 'gestor' and getattr(profile, 'setor', None) == 'suporte')

def _buscar_suportes_do_cliente(cliente, user=None):
    is_master = False
    if user and user.is_authenticated:
        is_master = _can_manage_all_users(user)

    suportes = ClienteSuporte.objects.none()
    cnpj_limpo = _digits_only(cliente.cnpj)
    if cnpj_limpo:
        suportes = ClienteSuporte.objects.filter(cnpj=cnpj_limpo)

    if (not suportes.exists()) and cliente.cpf:
        cpf_limpo = _digits_only(cliente.cpf)
        if cpf_limpo:
            suportes = ClienteSuporte.objects.filter(cnpj=cpf_limpo)

    if (not suportes.exists()) and cliente.nome:
        suportes = ClienteSuporte.objects.filter(nome__iexact=cliente.nome.strip())

    if (not suportes.exists()) and cliente.email:
        suportes = ClienteSuporte.objects.filter(email__iexact=cliente.email.strip())

    if not suportes.exists(): return []

    suportes = suportes.order_by("-updated_at", "-id")
    items = []
    for suporte in suportes:
        ocorrencias_list = []
        historico_list = []
        if suporte.serial and suporte.serial.strip():
            serial_limpo = suporte.serial.strip()
            ocorrencias_db = Record.objects.filter(serial__iexact=serial_limpo).order_by("-data")
            for oco in ocorrencias_db:
                ocorrencias_list.append({
                    "id": oco.id, "data_reporte": oco.data, "data_conclusao": oco.finished,
                    "reportado_por": oco.technical or "Não identificado", "responsavel": oco.responsible or "Não identificado",
                    "erro_resumo": oco.problem_detected, "solucao": oco.solution,
                })
            buscas_db = SerialSearchLog.objects.filter(searched_serial__iexact=serial_limpo).select_related('user').order_by("-created_at")
            for busca in buscas_db:
                historico_list.append({ "data": busca.created_at, "usuario": busca.user.username if busca.user else "Sistema" })

        items.append({
            "id": suporte.id, "serial": suporte.serial, "serial_sec": suporte.serial_sec,
            "equipamento": suporte.equipamento, "ativacao": getattr(suporte, "data", None),
            "vencimento": suporte.vencimento, "status_label": _status_label(suporte),
            "status_class": _status_class(suporte), "ocorrencias": ocorrencias_list,
            "ocorrencias_count": len(ocorrencias_list), "historico": historico_list,
            "historico_count": len(historico_list), "is_master": is_master,
        })
    return items

@login_required
@require_system_access('clientes')
def painel_clientes(request):
    try:
        busca = (request.GET.get("q") or "").strip()
        modo = (request.GET.get("view") or "kanban").strip().lower()
        tipo = request.GET.get("tipo")
        profissao_filtro = request.GET.get("profissao")
        min_equip = request.GET.get("min_equip")
        max_equip = request.GET.get("max_equip")
        sincronizado = request.GET.get("sincronizado")
        no_site = request.GET.get("no_site")
        consultado = request.GET.get("consultado")
        data_inicio = request.GET.get("data_inicio")
        data_fim = request.GET.get("data_fim")
        teve_compra = request.GET.get("teve_compra")
        gasto_min = request.GET.get("gasto_min")
        compra_inicio = request.GET.get("compra_inicio")
        compra_fim = request.GET.get("compra_fim")
        
        status_equip_selecionados = request.GET.getlist("status_equip")
        equipamentos_selecionados = request.GET.getlist("equipamento")
        produtos_selecionados = request.GET.getlist("produtos_shopify")
        has_serial_sec = request.GET.get("has_serial_sec")

        if modo not in {"kanban", "lista"}: modo = "kanban"

        user = request.user
        clientes_qs = Cliente.objects.all()

        # 1. Filtros de Texto / Identidade
        if busca:
            q_global = Q(nome__icontains=busca) | Q(razao_social__icontains=busca) | Q(email__icontains=busca) | \
                       Q(telefone__icontains=busca) | Q(cpf__icontains=busca) | Q(cnpj__icontains=busca) | \
                       Q(cidade__icontains=busca) | Q(uf__icontains=busca) | Q(profissao__icontains=busca)
            
            suportes_ids = ClienteSuporte.objects.filter(Q(serial__icontains=busca) | Q(serial_sec__icontains=busca))
            if suportes_ids.exists():
                cpfs = list(suportes_ids.exclude(cnpj="SEM DADO").values_list('cnpj', flat=True))
                emails = list(suportes_ids.exclude(email__isnull=True).exclude(email="").values_list('email', flat=True))
                nomes = list(suportes_ids.values_list('nome', flat=True))
                if cpfs: q_global |= Q(cpf__in=cpfs) | Q(cnpj__in=cpfs)
                if emails: q_global |= Q(email__in=emails)
                if nomes: q_global |= Q(nome__in=nomes)
            clientes_qs = clientes_qs.filter(q_global)

        # 2. Filtros de Atributos do Cliente
        if tipo == "pf": clientes_qs = clientes_qs.filter(cpf__isnull=False).exclude(cpf="")
        elif tipo == "pj": clientes_qs = clientes_qs.filter(cnpj__isnull=False).exclude(cnpj="")
        if profissao_filtro: clientes_qs = clientes_qs.filter(profissao=profissao_filtro)
        if sincronizado == "true": clientes_qs = clientes_qs.filter(odoo_partner_id__isnull=False)
        elif sincronizado == "false": clientes_qs = clientes_qs.filter(odoo_partner_id__isnull=True)
        if no_site == "true": clientes_qs = clientes_qs.exclude(email="").exclude(email__isnull=True)
        elif no_site == "false": clientes_qs = clientes_qs.filter(Q(email="") | Q(email__isnull=True))

        # 3. Filtros de Equipamentos (Múltipla Escolha e Seriais)
        if has_serial_sec == "true":
            sup_sec = ClienteSuporte.objects.exclude(serial_sec="").exclude(serial_sec__isnull=True)
            c_sec = list(sup_sec.exclude(cnpj="SEM DADO").values_list('cnpj', flat=True))
            e_sec = list(sup_sec.exclude(email__isnull=True).exclude(email="").values_list('email', flat=True))
            clientes_qs = clientes_qs.filter(Q(cpf__in=c_sec) | Q(cnpj__in=c_sec) | Q(email__in=e_sec))

        if equipamentos_selecionados:
            sup_model = ClienteSuporte.objects.filter(equipamento__in=equipamentos_selecionados)
            c_ids = list(sup_model.exclude(cnpj="SEM DADO").values_list('cnpj', flat=True))
            e_ids = list(sup_model.exclude(email__isnull=True).exclude(email="").values_list('email', flat=True))
            clientes_qs = clientes_qs.filter(Q(cpf__in=c_ids) | Q(cnpj__in=c_ids) | Q(email__in=e_ids))

        if status_equip_selecionados:
            from django.utils import timezone
            today = timezone.now().date()
            vencendo_limit = today + timezone.timedelta(days=15)
            
            status_q = Q()
            if 'direito' in status_equip_selecionados:
                status_q |= Q(vencimento__gte=today)
            if 'vencendo' in status_equip_selecionados:
                status_q |= Q(vencimento__gte=today, vencimento__lte=vencendo_limit)
            if 'vencido' in status_equip_selecionados:
                status_q |= Q(vencimento__lt=today) | Q(equipment_status='bloqueado')
            if 'bloqueado_data_invalida' in status_equip_selecionados:
                status_q |= Q(equipment_status='bloqueado_data_invalida')
            
            sup_st = ClienteSuporte.objects.filter(status_q)
            c_st = list(sup_st.exclude(cnpj="SEM DADO").values_list('cnpj', flat=True))
            e_st = list(sup_st.exclude(email__isnull=True).exclude(email="").values_list('email', flat=True))
            clientes_qs = clientes_qs.filter(Q(cpf__in=c_st) | Q(cnpj__in=c_st) | Q(email__in=e_st))

        # 4. Filtros de Auditoria / Consultas
        if consultado in ["true", "false"] or data_inicio or data_fim:
            log_qs = SerialSearchLog.objects.all()
            if data_inicio: log_qs = log_qs.filter(created_at__date__gte=data_inicio)
            if data_fim: log_qs = log_qs.filter(created_at__date__lte=data_fim)
            seriais = list(log_qs.values_list('searched_serial', flat=True).distinct())
            if seriais:
                suportes_v = ClienteSuporte.objects.filter(Q(serial__in=seriais) | Q(serial_sec__in=seriais))
                cpfs_v = list(suportes_v.exclude(cnpj="SEM DADO").values_list('cnpj', flat=True))
                emails_v = list(suportes_v.exclude(email__isnull=True).exclude(email="").values_list('email', flat=True))
                q_cons = Q(cpf__in=cpfs_v) | Q(cnpj__in=cpfs_v) | Q(email__in=emails_v)
                clientes_qs = clientes_qs.exclude(q_cons) if consultado == "false" else clientes_qs.filter(q_cons)
            elif consultado == "true": clientes_qs = clientes_qs.none()

        # 5. Filtros de E-commerce (Shopify)
        if teve_compra in ["true", "false"] or gasto_min or compra_inicio or produtos_selecionados:
            try:
                shopify = _get_shopify_client()
                if shopify:
                    sq = []
                    if teve_compra == "true": sq.append("total_spent:>0")
                    if gasto_min: sq.append(f"total_spent:>{gasto_min}")
                    if compra_inicio: sq.append(f"created_at:>={compra_inicio}")
                    if produtos_selecionados:
                        for prod in produtos_selecionados: sq.append(f"product_title:'{prod}'")

                    emails_s = shopify.search_customers(" AND ".join(sq) if sq else "total_spent:>0", first=250)
                    if emails_s:
                        if teve_compra == "false": clientes_qs = clientes_qs.exclude(email__in=emails_s)
                        else: clientes_qs = clientes_qs.filter(email__in=emails_s)
                    elif teve_compra == "true" or produtos_selecionados:
                        clientes_qs = clientes_qs.none()
            except: pass

        # Annotations para contagem
        if _can_view_all_orcamentos(user):
            clientes_qs = clientes_qs.annotate(orcamentos_count=Count('registros_orcamento', distinct=True))
        elif _is_colaborador_comercial(user):
            clientes_qs = clientes_qs.annotate(orcamentos_count=Count('registros_orcamento', filter=Q(registros_orcamento__vendas__vendedor=user), distinct=True))
        else:
            clientes_qs = clientes_qs.annotate(orcamentos_count=Value(0, output_field=IntegerField()))

        clientes_qs = clientes_qs.order_by("-atualizado_em").distinct()
        paginator = Paginator(clientes_qs, 12)
        page_obj = paginator.get_page(request.GET.get("page"))

        clientes_render = []
        for c in page_obj.object_list:
            sups = _buscar_suportes_do_cliente(c)
            count = len(sups)
            if min_equip and count < int(min_equip): continue
            if max_equip and count > int(max_equip): continue
            clientes_render.append({
                "obj": c, "tipo_doc": "PJ" if c.cnpj else ("PF" if c.cpf else "Sem doc"),
                "documento": _formatar_documento(c.cnpj or c.cpf or ""),
                "telefone_formatado": _formatar_telefone(c.telefone or ""),
                "suportes_count": count, "orcamentos_count": getattr(c, 'orcamentos_count', 0),
            })

        profissoes = Cliente.objects.exclude(profissao="").values_list('profissao', flat=True).distinct().order_by('profissao')
        lista_equipamentos = ClienteSuporte.objects.exclude(equipamento="").values_list('equipamento', flat=True).distinct().order_by('equipamento')
        
        lista_produtos_shopify = []
        try:
            shopify = _get_shopify_client()
            if shopify: lista_produtos_shopify = shopify.list_products()
        except: pass

        # Prepara querystring para a paginação não quebrar os filtros
        params = request.GET.copy()
        if "page" in params: del params["page"]
        querystring = params.urlencode()

        return render(request, "clientes/painel_clientes.html", {
            "page_obj": page_obj, "clientes_render": clientes_render, "busca": busca, "view_mode": modo, "tipo": tipo,
            "profissao_filtro": profissao_filtro, "sincronizado": sincronizado, "no_site": no_site, "consultado": consultado,
            "data_inicio": data_inicio, "data_fim": data_fim, "teve_compra": teve_compra, "gasto_min": gasto_min,
            "compra_inicio": compra_inicio, "compra_fim": compra_fim, 
            "status_equip_selecionados": status_equip_selecionados, 
            "min_equip": min_equip, "max_equip": max_equip, 
            "equipamentos_selecionados": equipamentos_selecionados, 
            "produtos_selecionados": produtos_selecionados,
            "has_serial_sec": has_serial_sec,
            "profissoes": profissoes, "lista_equipamentos": lista_equipamentos, "lista_produtos_shopify": lista_produtos_shopify,
            "total_clientes": clientes_qs.count(),
            "total_pf": Cliente.objects.filter(cpf__isnull=False).exclude(cpf="").count(),
            "total_pj": Cliente.objects.filter(cnpj__isnull=False).exclude(cnpj="").count(),
            "total_odoo": Cliente.objects.filter(odoo_partner_id__isnull=False).count(),
            "querystring": querystring,
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Erro no painel: {e}", exc_info=True)
        return render(request, "clientes/painel_clientes.html", {"error": str(e)})


def delete_orcamento(request, orcamento_id):
    if not request.user.is_authenticated: return JsonResponse({"error": "Não autorizado"}, status=403)
    if not (_is_dono(request.user) or _is_diretor(request.user) or _is_gestor_ti(request.user)):
        return JsonResponse({"error": "Sem permissão para excluir"}, status=403)
    orcamento = get_object_or_404(Registro, pk=orcamento_id)
    cid = orcamento.cliente_id
    try:
        orcamento.delete()
        from django.contrib import messages
        messages.success(request, "Orçamento excluído.")
    except Exception as e:
        from django.contrib import messages
        messages.error(request, f"Erro: {e}")
    return redirect("clientes:detalhe", cliente_id=cid) if cid else redirect("clientes:painel")

def _get_odoo_client():
    return OdooClient(OdooConfig(url=settings.ODOO_URL, db=settings.ODOO_DB, username=settings.ODOO_USER, password=settings.ODOO_PASSWORD))

def _get_shopify_client():
    if not settings.SHOPIFY_STORE_URL or not settings.SHOPIFY_ACCESS_TOKEN: return None
    return ShopifyClient(settings.SHOPIFY_STORE_URL, settings.SHOPIFY_ACCESS_TOKEN)

@login_required
@require_system_access('clientes')
def detalhe_cliente(request, cliente_id):
    user = request.user
    user_token = ""
    if request.user.is_authenticated:
        token_obj, _ = Token.objects.get_or_create(user=request.user)
        user_token = token_obj.key
    can_view_all = _can_view_all_orcamentos(user)
    is_comercial = _is_colaborador_comercial(user)
    can_view_orcamentos = can_view_all or is_comercial
    orc_qs = Registro.objects.none()
    if can_view_all: orc_qs = Registro.objects.prefetch_related("vendas").order_by("-criado_em")
    elif is_comercial: orc_qs = Registro.objects.filter(vendas__vendedor=user).prefetch_related("vendas").distinct().order_by("-criado_em")
    cliente = get_object_or_404(Cliente.objects.prefetch_related("enderecos", Prefetch("registros_orcamento", queryset=orc_qs)), pk=cliente_id)
    if request.method == "POST" and "odoo_id" in request.POST:
        oid = request.POST.get("odoo_id").strip()
        if oid.isdigit():
            cliente.odoo_partner_id = int(oid)
            cliente.save(update_fields=["odoo_partner_id", "atualizado_em"])
            return redirect("clientes:detalhe", cliente_id=cliente.id)
    suportes = _buscar_suportes_do_cliente(cliente, request.user)
    extras = cliente.enderecos.filter(is_ativo=True).order_by("-is_padrao_entrega", "nome")
    orcamentos = cliente.registros_orcamento.all()
    p_odoo, e_odoo = [], []
    if cliente.odoo_partner_id:
        try:
            odoo = _get_odoo_client()
            p_odoo = odoo.buscar_pedidos_venda_por_partner(cliente.odoo_partner_id)
            main = odoo.partner_read(cliente.odoo_partner_id, ["id", "name", "type", "street", "l10n_br_endereco_numero", "street2", "l10n_br_endereco_bairro", "city", "state_id", "zip"])
            e_odoo = odoo.buscar_contatos_filhos(cliente.odoo_partner_id)
            if main and main.get("street"):
                main["type"] = "Faturamento/Principal"
                e_odoo.insert(0, main)
        except: pass
    shopify_data = None
    if cliente.email:
        try:
            shopify = _get_shopify_client()
            if shopify:
                shopify_data = shopify.get_customer_data(cliente.email)
                if shopify_data and shopify_data.get("orders"):
                    for ped in shopify_data["orders"]:
                        if ped.get("token_serials"):
                            for s_info in ped["token_serials"]:
                                parts = s_info.split(": ", 1)
                                prod_nome = parts[0] if len(parts) > 1 else "Token Shopify"
                                s_val = (parts[1] if len(parts) > 1 else parts[0]).strip().lower()
                                for sup in suportes:
                                    if str(sup.get("serial") or "").strip().lower() == s_val:
                                        if "tokens_shopify" not in sup: sup["tokens_shopify"] = []
                                        sup["tokens_shopify"].append({"equipamento": prod_nome, "ativacao": ped["date"], "pedido_origem": ped["name"]})
                                        break
        except: pass
    total_e = len(extras) + len(e_odoo)
    can_sync = request.user.is_authenticated and (_is_dono(user) or _is_diretor(user) or _is_gestor_ti(user))
    return render(request, "clientes/detalhe_cliente.html", {
        "cliente": cliente, "suportes": suportes, "enderecos_extras": extras, "orcamentos": orcamentos,
        "pedidos_odoo": p_odoo, "enderecos_odoo": e_odoo, "shopify_data": shopify_data, "total_enderecos": total_e,
        "can_sync_odoo": can_sync, "can_view_orcamentos": can_view_orcamentos, "user_token": user_token,
    })

def sync_odoo_cliente(request, cliente_id):
    from .services.odoo_sync import ensure_odoo_partner_for_cliente
    from django.contrib import messages
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    if not (_is_dono(request.user) or _is_diretor(request.user) or _is_gestor_ti(request.user)):
        messages.error(request, "Sem permissão.")
        return redirect("clientes:detalhe", cliente_id=cliente.id)
    try:
        pid = ensure_odoo_partner_for_cliente(cliente, always_update_local=True)
        messages.success(request, f"Sucesso! ID Odoo: {pid}")
    except Exception as e: messages.error(request, f"Erro: {e}")
    return redirect("clientes:detalhe", cliente_id=cliente.id)

def enrich_cliente_api(request, cliente_id):
    """ View para enriquecer dados do cliente via CNPJA sem depender do Odoo """
    from .services.odoo_sync import enrich_cliente_from_cnpj, RateLimitError
    from django.contrib import messages
    cliente = get_object_or_404(Cliente, pk=cliente_id)
    try:
        changed = enrich_cliente_from_cnpj(cliente)
        if changed:
            messages.success(request, "Dados atualizados com sucesso via API!")
        else:
            messages.info(request, "Não foram encontradas novas informações.")
    except RateLimitError as e:
        messages.warning(request, str(e))
    except Exception as e:
        messages.error(request, f"Erro ao consultar API: {e}")
    return redirect("clientes:detalhe", cliente_id=cliente.id)

import hashlib
import hmac
import json
from django.views.decorators.csrf import csrf_exempt
from .services.shopify_sync import ShopifySyncService

import threading

@login_required
@require_system_access('clientes')
def sync_shopify_clientes(request):
    """
    Inicia a sincronização completa do Shopify em background.
    """
    if not (_is_dono(request.user) or _is_diretor(request.user) or _is_gestor_ti(request.user)):
        return JsonResponse({"error": "Sem permissão"}, status=403)
    
    def run_sync():
        try:
            service = ShopifySyncService()
            count = service.sync_all_customers()
            print(f"[SHOPIFY SYNC] Finalizado: {count} clientes.")
        except Exception as e:
            print(f"[SHOPIFY SYNC] ERRO: {e}")

    # Dispara a thread em background para não travar o servidor
    thread = threading.Thread(target=run_sync)
    thread.daemon = True # A thread morre se o processo principal do Django parar
    thread.start()

    from django.contrib import messages
    messages.info(request, "Sincronização Shopify iniciada em background. Pode demorar alguns minutos.")
    
    return redirect("clientes:painel")


@login_required
@require_system_access('clientes')
def sync_all_to_odoo(request):
    """
    Inicia a sincronização completa de TODOS os clientes locais com o Odoo em background.
    """
    if not (_is_dono(request.user) or _is_diretor(request.user) or _is_gestor_ti(request.user)):
        return JsonResponse({"error": "Sem permissão"}, status=403)
    
    def run_sync():
        try:
            from .services.odoo_sync import sync_all_local_to_odoo
            count = sync_all_local_to_odoo()
            print(f"[ODOO MASS SYNC] Finalizado: {count} clientes processados.")
        except Exception as e:
            print(f"[ODOO MASS SYNC] ERRO: {e}")

    # Thread para não travar a UI
    thread = threading.Thread(target=run_sync)
    thread.daemon = True
    thread.start()

    from django.contrib import messages
    messages.info(request, "Sincronização em massa com Odoo iniciada. O sistema processará todos os clientes em background.")
    
    return redirect("clientes:painel")


@csrf_exempt
def shopify_webhook(request):
    """
    Recebe notificações do Shopify sobre criação/atualização de clientes.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # 1. Verificar HMAC (Segurança)
    shopify_hmac = request.headers.get("X-Shopify-Hmac-Sha256")
    if not shopify_hmac:
        return JsonResponse({"error": "Missing HMAC header"}, status=401)

    # O Shopify Access Token não é o segredo do webhook.
    # O segredo do webhook geralmente é configurado manualmente ou via API.
    # Mas aqui vamos usar o que o usuário tiver configurado em settings.
    webhook_secret = getattr(settings, "SHOPIFY_WEBHOOK_SECRET", None)
    
    body = request.body
    if webhook_secret:
        hash_calc = hmac.new(webhook_secret.encode('utf-8'), body, hashlib.sha256).digest()
        import base64
        calculated_hmac = base64.b64encode(hash_calc).decode()
        
        if not hmac.compare_digest(calculated_hmac, shopify_hmac):
            return JsonResponse({"error": "Invalid HMAC"}, status=401)

    # 2. Processar Dados
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    topic = request.headers.get("X-Shopify-Topic")
    
    # Normalizar dados do Shopify REST (Webhooks usam REST JSON, não GraphQL)
    # Mas o ShopifySyncService espera um formato similar ao GraphQL nodes.
    # Vamos converter o formato do webhook para o formato que o service entende.
    
    cust_data = {
        "id": f"gid://shopify/Customer/{data.get('id')}",
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "display_name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "created_at": data.get("created_at"),
        "addresses": [
            {
                "address1": addr.get("address1"),
                "address2": addr.get("address2"),
                "city": addr.get("city"),
                "provinceCode": addr.get("province_code"),
                "zip": addr.get("zip"),
                "country": addr.get("country")
            } for addr in data.get("addresses", [])
        ]
    }

    sync_service = ShopifySyncService()
    cliente = sync_service.update_or_create_cliente(cust_data)

    if cliente:
        return JsonResponse({"status": "ok", "cliente_id": cliente.id})
    else:
        return JsonResponse({"status": "ignored", "message": "No email found"}, status=200)


@login_required
@require_system_access('clientes')
def ajax_load_shopify_orders(request):
    email, cursor = request.GET.get("email"), request.GET.get("cursor")
    if not email: return JsonResponse({"error": "E-mail ausente"}, status=400)
    try:
        shopify = _get_shopify_client()
        if not shopify: return JsonResponse({"error": "Configuração Shopify ausente"}, status=500)
        data = shopify.get_customer_data(email, cursor=cursor)
        return JsonResponse({"orders": data["orders"] if data else [], "has_next_page": data["has_next_page"] if data else False, "end_cursor": data["end_cursor"] if data else None})
    except Exception as e: return JsonResponse({"error": str(e)}, status=500)
