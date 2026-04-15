# pedido/views.py
from __future__ import annotations
import json
from urllib.parse import urljoin
import requests
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required

from painel.decorators import require_system_access

from .models import Venda
from simulador.models import Registro
from clientes.models import Cliente, ClienteEndereco

from django.conf import settings
from clientes.integrations.odoo_client import OdooClient, OdooConfig
import re
from .utils.pagamento import gerar_token_interno_pagamento, obter_access_token_rede, gerar_payload_pix_rede, consultar_pix_rede, registrar_notification_url_rede_sandbox, obter_credenciais_rede

from django.urls import reverse

from datetime import timedelta
from django.utils import timezone

from requests.auth import HTTPBasicAuth
import uuid

try:
    from weasyprint import HTML
except ImportError:
    HTML = None

import logging
logger = logging.getLogger(__name__)

URL_LOGIN = '/login/'  # Substitua pela URL real de login do seu projeto


def _env_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _confirmar_pedido_no_odoo(venda) -> dict:
    if not getattr(venda, "odoo_sale_order_id", None):
        return {"ok": False, "message": "Venda sem odoo_sale_order_id."}

    try:
        odoo = _odoo_client()
        odoo.sale_order_action_confirm(int(venda.odoo_sale_order_id))

        return {
            "ok": True,
            "message": f"Venda criada no Odoo com sucesso. Pedido #{venda.odoo_sale_order_id}.",
            "venda_id": venda.id,
            "odoo_sale_order_id": venda.odoo_sale_order_id,
            "status": venda.status,
            "status_pagamento": venda.status_pagamento,
            "hide_registro": True,
        }
    except Exception as e:
        return {"ok": False, "message": str(e)}

def _validar_auth_webhook_rede(request: HttpRequest) -> bool:
    auth_enabled = _env_bool(getattr(settings, "REDE_WEBHOOK_AUTH_ENABLED", getattr(settings, "REDE_WEBHOOK_USE_AUTH", False)), False)
    if not auth_enabled:
        return True

    expected = str(getattr(settings, "REDE_WEBHOOK_AUTH_TOKEN", "") or "").strip()
    received = str(request.headers.get("Authorization", "") or "").strip()

    return bool(expected) and received == expected

def _buscar_venda_por_pix_tid_ou_reference(tid: str = "", reference: str = "") -> Venda | None:
    tid = str(tid or "").strip()
    reference = str(reference or "").strip()

    if tid:
        venda = (
            Venda.objects.filter(Q(pix_tid=tid) | Q(rede_tid=tid))
            .order_by("-id")
            .first()
        )
        if venda:
            return venda

    if reference:
        venda = Venda.objects.filter(rede_reference=reference).order_by("-id").first()
        if venda:
            return venda

    return None

def _gerar_ou_reaproveitar_link_pagamento(request: HttpRequest, venda: Venda, forma_pagamento: str, forcar_novo: bool = False) -> str | None:
    forma = (forma_pagamento or "").strip().lower()

    eh_pix = forma == "pix"
    eh_cartao = forma in ["cartao", "cartão", "cartao de credito", "cartão de crédito"]
    eh_boleto = forma == "boleto"

    if eh_boleto:
        venda.marcar_status_odoo()
        venda.save(update_fields=[
            "status",
            "status_pagamento",
            "token_pagamento",
            "link_pagamento",
        ])

        confirmacao_odoo = {"ok": True}
        try:
            confirmacao_odoo = _confirmar_pedido_no_odoo(venda)
        except Exception as e:
            logger.warning("Erro ao confirmar pedido no Odoo (boleto): %s", e)
            confirmacao_odoo = {"ok": False, "message": str(e)}

        return {
            "tipo": "odoo",
            "message": f"Venda enviada para o Odoo com sucesso. Pedido #{venda.odoo_sale_order_id}",
            "odoo_sale_order_id": venda.odoo_sale_order_id,
            "status": venda.status,
            "remover_registro": True,
            "confirmacao_odoo": confirmacao_odoo,
        }

    if not (eh_pix or eh_cartao):
        venda.token_pagamento = None
        venda.link_pagamento = None
        venda.limpar_dados_pix()
        venda.save(update_fields=[
            "token_pagamento",
            "link_pagamento",
            "codigo_pix",
            "codigo_pix_imagem",
            "pix_tid",
            "pix_expira_em",
            "rede_reference",
            "rede_tid",
            "rede_nsu",
            "rede_authorization_code",
        ])
        return None

    token_atual = (getattr(venda, "token_pagamento", None) or "").strip()

    if not token_atual or forcar_novo:
        token_atual = gerar_token_interno_pagamento()
        venda.token_pagamento = token_atual

    rota_pagamento = "pedido:pagina_pagamento_pix" if eh_pix else "pedido:pagina_pagamento_cartao"
    path_pagamento = reverse(rota_pagamento, kwargs={"token": token_atual})
    link_pagamento = request.build_absolute_uri(path_pagamento)
    logger.warning("LINK PAGAMENTO FINAL: %s", link_pagamento)

    venda.link_pagamento = link_pagamento
    venda.status = Venda.StatusChoices.COTACAO
    venda.status_pagamento = Venda.StatusPagamentoChoices.PENDENTE

    if eh_pix and forcar_novo:
        venda.limpar_dados_pix()

    venda.save()
    return link_pagamento

def _confirmar_pagamento_3ds(venda):
    tid_limpo = (venda.rede_tid or "").strip()
    ref_limpa = (venda.rede_reference or "").strip()

    if not (tid_limpo or ref_limpa):
        return {
            "ok": False,
            "approved": False,
            "message": "Venda sem TID ou reference.",
            "raw": {},
        }

    pv, token_rede, sandbox = obter_credenciais_rede()
    rede_url = (
        "https://sandbox-erede.useredecloud.com.br/v2/transactions"
        if sandbox
        else "https://api.userede.com.br/erede/v2/transactions"
    )

    print(rede_url, pv, token_rede)

    # =========================================================
    # 1. BUSCA O TOKEN OAUTH 2.0 ANTES DA REQUISIÇÃO
    # =========================================================
    token_response = obter_access_token_rede()
    if not token_response.get("ok"):
        return {
            "ok": False,
            "approved": False,
            "message": f"Erro de autenticação OAuth: {token_response.get('message')}",
            "raw": {},
        }
    access_token = token_response.get("access_token")
    # =========================================================

    raw = {}

    try:
        if tid_limpo:
            logger.warning(f"Consultando Rede pelo TID: {tid_limpo}")
            resp = requests.get(
                f"{rede_url}/{tid_limpo}",
                # 2. SUBSTITUI O BASIC AUTH PELO BEARER TOKEN
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                },
                timeout=15,
            )
            logger.warning("resp.status_code: %s", resp.status_code)
            logger.warning("resp.text: %s", resp.text[:3000])
            logger.warning("STATUS CONSULTA TID: %s", resp.status_code)
            logger.warning("BODY CONSULTA TID: %s", resp.text[:2000])
            if resp.ok:
                raw = resp.json()

        elif ref_limpa:
            logger.warning(f"Consultando Rede pela Reference: {ref_limpa}")
            resp = requests.get(
                f"{rede_url}?reference={ref_limpa}",
                # 2. SUBSTITUI O BASIC AUTH PELO BEARER TOKEN
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json"
                },
                timeout=15,
            )
            logger.warning(f"STATUS CONSULTA REF: {resp.status_code}")
            logger.warning(f"BODY CONSULTA REF: {resp.text[:2000]}")

            if resp.ok:
                data = resp.json()

                # formato 1: resposta já vem como objeto de transação
                if isinstance(data, dict) and (
                    "authorization" in data or "capture" in data or "threeDSecure" in data
                ):
                    raw = data

                # formato 2: resposta vem como lista em transactions
                elif isinstance(data, dict) and "transactions" in data:
                    transacoes = data.get("transactions", [])
                    if isinstance(transacoes, list) and transacoes:
                        raw = transacoes[0]

                # formato 3: resposta vem direto como lista
                elif isinstance(data, list) and data:
                    raw = data[0]

    except Exception as e:
        return {
            "ok": False,
            "approved": False,
            "message": f"Erro ao consultar Rede: {e}",
            "raw": raw,
        }

    if not raw:
        return {
            "ok": False,
            "approved": False,
            "message": "A Rede não retornou dados da transação.",
            "raw": raw,
        }

    auth = raw.get("authorization", {}) if isinstance(raw, dict) else {}

    return_code = str(
        auth.get("returnCode") or raw.get("returnCode", "")
    ).strip()

    return_message = str(
        auth.get("returnMessage") or raw.get("returnMessage", "")
    ).strip()

    logger.warning("RETORNO REDE: %s", raw)
    logger.warning("venda.rede_tid: %s", venda.rede_tid)
    logger.warning("venda.rede_reference: %s", venda.rede_reference)
    logger.warning("venda.status: %s", venda.status)
    logger.warning("venda.status_pagamento: %s", venda.status_pagamento)
    if return_code == "00":
        venda.rede_tid = auth.get("tid", "") or raw.get("tid", "") or tid_limpo
        venda.rede_nsu = auth.get("nsu", "") or raw.get("nsu", "")
        venda.rede_authorization_code = auth.get("authorizationCode", "") or raw.get("authorizationCode", "")

        venda.marcar_pago()
        venda.save(update_fields=[
            "rede_tid",
            "rede_nsu",
            "rede_authorization_code",
            "status",
            "status_pagamento",
            "token_pagamento",
            "link_pagamento",
        ])

        try:
            _confirmar_pedido_no_odoo(venda)
        except Exception as e:
            logger.warning("Erro ao confirmar pedido no Odoo: %s", e)

        try:
            valor_base = sum(
                float(eq.get("valor_total", 0) or 0)
                for eq in (venda.equipamentos_json or [])
            )
            _enviar_comprovante_pagamento_rede_para_odoo(venda, raw, valor_base)
        except Exception as e:
            logger.warning("Erro ao enviar comprovante ao Odoo: %s", e)

        return {
            "ok": True,
            "approved": True,
            "message": return_message or "Pagamento aprovado.",
            "raw": raw,
        }

    if return_code in {"05", "57", "78", "70", "99"}:
        if hasattr(venda, "marcar_pagamento_recusado"):
            venda.marcar_pagamento_recusado()
            venda.save(update_fields=["status", "status_pagamento"])

    return {
        "ok": True,
        "approved": False,
        "message": return_message or f"Pagamento ainda não aprovado. returnCode={return_code}",
        "raw": raw,
    }

def _agendar_aprovacao_comercial_no_odoo(venda) -> dict:
    if not getattr(venda, "odoo_sale_order_id", None):
        return {
            "ok": False,
            "message": "Venda sem odoo_sale_order_id.",
        }

    try:
        odoo = _odoo_client()
        login_odoo = "adm.vendasbr@eaata.pro"
        usuario_odoo = odoo.buscar_usuario_odoo(login_odoo)
        if not usuario_odoo:
            return {
                "ok": False,
                "message": f"Usuário '{login_odoo}' não encontrado no Odoo.",
            }

        user_id = int(usuario_odoo["id"])

        activity_id = odoo.agendar_atividade_pedido(
            sale_order_id=int(venda.odoo_sale_order_id),
            user_id=user_id,
            summary="Conceder aprovação",
            note=f"Cotação #{venda.odoo_sale_order_id} criada no painel. Conceder aprovação.",
        )

        logger.warning("===================================")
        logger.warning("ATIVIDADE DE APROVAÇÃO AGENDADA NO ODOO")
        logger.warning("sale_order_id: %s", venda.odoo_sale_order_id)
        logger.warning("user_id: %s", user_id)
        logger.warning("usuario: %s", usuario_odoo)
        logger.warning("activity_id: %s", activity_id)
        logger.warning("===================================")

        return {
            "ok": True,
            "activity_id": activity_id,
            "user_id": user_id,
            "usuario": usuario_odoo,
            "message": "Atividade criada com sucesso.",
        }

    except Exception as e:
        logger.warning("ERRO AO AGENDAR APROVAÇÃO NO ODOO: %s", repr(e))
        return {
            "ok": False,
            "message": str(e),
        }
    
def _registro_ids_com_venda_bloqueada():
    """
    Registros que já viraram venda e não devem mais aparecer como opção no index.
    """
    return (
        Venda.objects.filter(
            status__in=[
                # REMOVA A LINHA DO AGUARDANDO_PAGAMENTO E DEIXE APENAS ESSES:
                Venda.StatusChoices.PAGAMENTO_PROCESSANDO,
                Venda.StatusChoices.PAGO,
                Venda.StatusChoices.CANCELADO,
                Venda.StatusChoices.ODOO,   # <- adicionar
            ]
        )
        .exclude(registro_origem__isnull=True)
        .values_list("registro_origem_id", flat=True)
    )

def traduzir_resumo_de_produtos(resumo_str: str) -> list[dict]:
    # ==========================================
    # 📚 DICIONÁRIO DE TRADUÇÃO (DE -> PARA)
    # Sempre use letras MAIÚSCULAS no lado esquerdo!
    # ==========================================
    DICIONARIO_DE_PARA = {
        # --- O SEU DICIONÁRIO ATUAL ---
        "CAMERA ES401": "THINKCAR ES401 VIDEO SCOPE",
        "ADAPTADOR TRAVA MQB": "ADAPTADOR VOLKSWAGEM MQB",
        "ADAPTADOR PROG360BOX - 1 ANO ATUALIZAÇÃO": "EAATA ADAPTADOR PROG360BOX", 
        "ADAPTADOR PROG360BOX - CLIENTE QUE JÁ TEM O ADAPTADOR - FRETE INCLUSO": "EAATA ADAPTADOR PROG360BOX",
        "AUXILIAR DE PARTIDA EAATA - TJS 120": "EAATA - TJS120 JUMPSTARTER",
        "MASTER 2": "THINKTOOL MASTER 2",
        "PROG": "THINKCAR - PROG 2",
        "MCU3": "THINKCAR - MCU 3",
        "01 (UM) ANO DE SUPORTE TÉCNICO": "SUPORTE ANUAL",
        "M-TESTER": "THINKEASY MAINTENANCE TESTER",
        "MACACO HIDRAULICO TFJ 340": "THINKCAR TFJ340 MACACO HIDRÁULICO",

        # --- A NOVA LISTA DE COMBOS E ATUALIZAÇÕES ---
        "TOKEN RENAULT - 10 TOKENS - 360 - EAATA 90 - THINKCAR": "TOKEN RENAULT - 10 TOKENS -360 - EAATA 90 THINKCAR",
        "PLATINUM S8 / THINKTOOL MASTER SE / THINKTOOL LITE / THINKTOOL LITE 2": "PLATINUM S8 / THINKTOOL MASTER SE / THINKTOOL LITE",
        "PLATINUM S10 / MASTER / THINKTOOL MASTER2": "PLATINUM S10 / MASTER / THINKTOOL MASTER 2",
        "PLATINUM S10 PRO E S20 / THINKTOOL MASTER X / MAX / 394 / 399": "PLATINUM S10 PRO / THINKTOOL MASTER X",
        
        "EAATA 360 PRO - 1 ANO ATUALIZAÇÃO": "COLOQUE O NOME AQUI (TAVA VAZIO)",
        "EAATA 90 - 1 ANO ATUALIZAÇÃO": "NOME DA ATUALIZAÇÃO EAATA 90 AQUI",
        
        "EV SOFTWARE 360 - ATIVAÇÃO OU 1 ANO DE ATUALIZAÇÃO": "EAATA - EV SOFTWARE 360",
        "EV SOFTWARE 1 ANO DE ATUALIZAÇÃO - THINKCAR": "NOME DO EV THINKCAR NO ODOO AQUI",
        "HD MASTER 2, X, MAX, 394 - PACOTE 1 ANO DE ATUALIZAÇÃO": "THINKCAR - HD FOR MAX AND MASTER X PACOTE ATIVACAO",
        "READER HD - ATUALIZAÇÃO PACOTE BRASIL - 1 ANO": "Reader HD - Atualização Pacote Brasil - 1 ano", 

        "ADAS THINKCAR - ATIVAÇÃO - MASTER2, MASTER X, MAX, 394, 399 E EAATA 90": "ADAS THINKCAR - ATIVAÇÃO",
        "ADAS 360 PRO - X431 - ATIVAÇÃO - CODE:701010027": "ADAS 360 PRO X431 - ATIVAÇÃO",
        "SFD VW - 1 ANO - 360-EAATA 90-THINKCAR (MASTER 2 OU X / MAX / 394 / 399)": "SFD VW - 1 ANO- 360-EAATA 90-THINKCAR (Master 2 ou X / MAX / 394 / 399)",

        # ==========================================
        # 🌟 PACOTES MULTI-PRODUTOS (USANDO LISTAS DEPOIS DOS DOIS PONTOS)
        # ==========================================
        "EAATA 360 PRO - COMBO 1 DE ATUALIZAÇÃO (VEÍCULOS DE PASSEIO + EV)": [
            "NOME DA ATUALIZAÇÃO DE PASSEIO DO 360 PRO NO ODOO",
            "EAATA - EV SOFTWARE 360"
        ],
        "394 E 399 - 1 ANO ATUALIZAÇÃO PACOTE (VEÍCULOS DE PASSEIO + HD)": [
            "PLATINUM S10 PRO / THINKTOOL MASTER X",
            "THINKCAR - PACOTE ATIVACAO MASTER LINHA PESADA HD"
        ],
        "394 E 399 - 1 ANO ATUALIZAÇÃO PACOTE (VEÍCULOS DE PASSEIO + EV)": [
            "PLATINUM S10 PRO / THINKTOOL MASTER X",
            "NOME DA ATUALIZAÇÃO EV NO ODOO"
        ],
        "394 E 399 - 1 ANO ATUALIZAÇÃO PACOTE (VEÍCULOS DE PASSEIO + EV + HD)": [
            "PLATINUM S10 PRO / THINKTOOL MASTER X",
            "NOME DA ATUALIZAÇÃO EV NO ODOO",
            "THINKCAR - PACOTE ATIVACAO MASTER LINHA PESADA HD"
        ],
    }
    
    produtos_finais = []
    if not resumo_str:
        return produtos_finais
        
    # 1. Separa os produtos pelas quantidades: (1x), (2x)
    matches = list(re.finditer(r'(.*?)\((\d+)x\)', resumo_str, re.IGNORECASE))
    
    if matches:
        for match in matches:
            # Pega o nome do bloco original e limpa vírgulas sobrando
            bloco_original = match.group(1).strip(' ,;')
            qtd = int(match.group(2))
            
            # Pega a versão em maiúsculo para checar no dicionário
            bloco_upper = bloco_original.upper()
            
            # ==========================================
            # 🛡️ PROTEÇÃO: Se a frase inteira estiver no dicionário (ex: pacotes com "+"), 
            # ele traduz direto e pula o fatiamento!
            # ==========================================
            if bloco_upper in DICIONARIO_DE_PARA:
                traducao = DICIONARIO_DE_PARA[bloco_upper]

                if isinstance(traducao, list):
                    for nome in traducao:
                        nome = str(nome or "").strip()
                        if nome:
                            produtos_finais.append({
                                "nome_busca": nome,
                                "qtd": qtd,
                            })
                else:
                    nome = str(traducao or "").strip()
                    if nome:
                        produtos_finais.append({
                            "nome_busca": nome,
                            "qtd": qtd,
                        })

                continue
                
            # 2. Se a frase não está no dicionário, aí sim ele divide pelo "+"
            partes = bloco_original.split('+')
            for parte in partes:
                # Remove as palavras "sujas" de campanha/brinde
                palavras_proibidas = r'(?i)\b(BRINDE|PROMO[CÇ][AÃ]O|CARNAVAL|MAR[CÇ]O)\b'
                nome_limpo = re.sub(palavras_proibidas, '', parte)
                
                # Limpa espaços e hifens soltos
                nome_limpo = re.sub(r'\s+', ' ', nome_limpo).strip()
                nome_limpo = re.sub(r'^-|-$', '', nome_limpo).strip()
                
                if nome_limpo:
                    # Checa o pedaço limpo no dicionário. Se não tiver, usa ele mesmo.
                    nome_traduzido = DICIONARIO_DE_PARA.get(nome_limpo.upper(), nome_limpo)

                    if isinstance(nome_traduzido, list):    
                        for nome in nome_traduzido:
                            nome = str(nome or "").strip()
                            if nome:
                                produtos_finais.append({
                                    "nome_busca": nome,
                                    "qtd": qtd,
                                })
                    else:
                        nome = str(nome_traduzido or "").strip()
                        if nome:
                            produtos_finais.append({
                                "nome_busca": nome,
                                "qtd": qtd,
                            })
    else:
        # Fallback de segurança (caso o texto venha sem o (1x) por algum motivo)
        bloco_limpo = re.sub(r'(?i)\b(BRINDE|PROMO[CÇ][AÃ]O|CARNAVAL|MAR[CÇ]O)\b', '', resumo_str)
        produtos_finais.append({"nome_busca": bloco_limpo.strip(' ,;-+'), "qtd": 1})
            
    return produtos_finais

def _categoria_odoo_por_profissao(profissao: str):
    prof = (profissao or "").strip().lower()

    if prof in ["chaveiro"]:
        return {
            "input_id": "category_id",
            "marker": "category_id_0_0",
            "nome": "Chaveiro",
        }

    if prof in ["mecanico", "mecânico"]:
        return {
            "input_id": "category_id",
            "marker": "category_id_0_1",
            "nome": "Mecânico",
        }

    return None

def _odoo_garantir_categoria_partner(odoo: OdooClient, partner_id: int, profissao: str) -> dict:
    categoria_cfg = _categoria_odoo_por_profissao(profissao)

    if not categoria_cfg:
        return {
            "categoria_cfg": None,
            "categoria_ok": None,
            "categoria_adicionada": False,
            "categoria_id_real": None,
            "categorias_atuais": [],
        }

    result = odoo.ensure_partner_category_by_name(
        int(partner_id),
        categoria_cfg["nome"],
    )

    return {
        "categoria_cfg": categoria_cfg,
        "categoria_ok": result["categoria_ok"],
        "categoria_adicionada": result["categoria_adicionada"],
        "categoria_id_real": result["category_id"],
        "categorias_atuais": result["categorias_atuais"],
    }

@require_http_methods(["GET", "POST"])
def api_odoo_testar_cliente(request: HttpRequest) -> JsonResponse:
    """
    Endpoint de teste:
    - procura partner no Odoo pelo CPF/CNPJ
    - se encontrar, valida a categoria conforme a profissão do painel
    - se faltar a categoria correta, adiciona no partner
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Não autenticado."}, status=401)
    def only_digits(v: str) -> str:
        return "".join(ch for ch in (v or "") if ch.isdigit())

    body = {}
    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8") or "{}")
        except Exception:
            body = {}

    raw = (
        body.get("doc")
        or body.get("documento")
        or body.get("cpf_cnpj")
        or body.get("query")
        or request.GET.get("doc")
        or request.GET.get("documento")
        or request.GET.get("cpf_cnpj")
        or request.GET.get("query")
        or ""
    )

    cliente_id = (
        body.get("cliente_id")
        or request.GET.get("cliente_id")
    )

    doc = only_digits(raw)

    if not cliente_id:
        return JsonResponse(
            {
                "ok": False,
                "message": "cliente_id é obrigatório.",
                "found": False,
                "partner_id": None,
            },
            status=400,
        )

    if len(doc) not in (11, 14):
        return JsonResponse(
            {
                "ok": False,
                "message": "Informe um CPF (11) ou CNPJ (14) válido.",
                "received_raw": raw,
                "received_digits": doc,
                "found": False,
                "partner_id": None,
            },
            status=400,
        )

    cliente = get_object_or_404(Cliente, pk=cliente_id)
    profissao = getattr(cliente, "profissao", "") or ""
    categoria_cfg = _categoria_odoo_por_profissao(profissao)

    tipo = "l10n_br_cpf" if len(doc) == 11 else "l10n_br_cnpj"

    try:
        odoo = _odoo_client()

        partner_id = odoo.find_partner_by_doc(
            tipo_faturamento=tipo,
            doc=doc,
            email=getattr(cliente, "email", None) or None,
            phone=getattr(cliente, "telefone", None) or None,
            name=getattr(cliente, "nome", None) or None,
        )

        if not partner_id:
            return JsonResponse(
                {
                    "ok": True,
                    "message": "cliente não encontrado",
                    "received_raw": raw,
                    "received_digits": doc,
                    "tipo": tipo,
                    "found": False,
                    "partner_id": None,
                    "profissao_painel": profissao,
                    "categoria_input_id": categoria_cfg["input_id"] if categoria_cfg else "category_id",
                    "categoria_marker": categoria_cfg["marker"] if categoria_cfg else None,
                    "categoria_esperada": categoria_cfg["nome"] if categoria_cfg else None,
                    "categoria_ok": None,
                    "categoria_adicionada": False,
                }
            )

        cat_result = _odoo_garantir_categoria_partner(
            odoo=odoo,
            partner_id=int(partner_id),
            profissao=profissao,
        )

        return JsonResponse(
            {
                "ok": True,
                "message": "cliente achado no odoo",
                "received_raw": raw,
                "received_digits": doc,
                "tipo": tipo,
                "found": True,
                "partner_id": int(partner_id),
                "profissao_painel": profissao,
                "categoria_input_id": categoria_cfg["input_id"] if categoria_cfg else "category_id",
                "categoria_marker": categoria_cfg["marker"] if categoria_cfg else None,
                "categoria_esperada": categoria_cfg["nome"] if categoria_cfg else None,
                "categoria_id_real": cat_result["categoria_id_real"],
                "categoria_ok": cat_result["categoria_ok"],
                "categoria_adicionada": cat_result["categoria_adicionada"],
                "categorias_atuais": cat_result["categorias_atuais"],
            }
        )

    except Exception as e:
        return JsonResponse(
            {
                "ok": False,
                "message": f"Erro ao consultar Odoo: {e}",
                "received_raw": raw,
                "received_digits": doc,
                "found": False,
                "partner_id": None,
            },
            status=500,
        )

def _registro_qs_do_usuario(request: HttpRequest):
    """
    Retorna um queryset de Registro filtrado SOMENTE para o usuário logado,
    independente do nome do campo no model Registro.
    """
    qs = Registro.objects.all()

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return qs.none()

    # tenta campos FK comuns
    for fk_name in ("vendedor", "user", "usuario", "created_by", "criado_por", "owner"):
        try:
            Registro._meta.get_field(fk_name)
            return qs.filter(**{fk_name: user})
        except Exception:
            pass

    # fallback: campo texto (nome do vendedor)
    for txt_name in ("nome_vendedor", "vendedor_nome", "usuario_nome"):
        try:
            Registro._meta.get_field(txt_name)

            # monta candidatos (username / get_username / __str__)
            candidates = []
            if hasattr(user, "username") and user.username:
                candidates.append(str(user.username))
            if hasattr(user, "get_username"):
                u = user.get_username()
                if u:
                    candidates.append(str(u))
            candidates.append(str(user))  # pode ser "Yago" (display)

            # limpa e remove duplicados
            cleaned = []
            for c in candidates:
                c = (c or "").strip()
                if c and c not in cleaned:
                    cleaned.append(c)

            if not cleaned:
                return qs.none()

            # ✅ case-insensitive OR entre candidatos
            q = Q()
            for c in cleaned:
                q |= Q(**{f"{txt_name}__iexact": c})

            # extra: se tiver "Nome Sobrenome", tenta também o primeiro token
            first = cleaned[0].split(" ")[0].strip()
            if first and len(first) >= 3:
                q |= Q(**{f"{txt_name}__iexact": first})

            return qs.filter(q)

        except Exception:
            pass

    # se não achar nada, não mostra nada (mais seguro)
    return qs.none()


def _only_digits(v: str) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def _odoo_client() -> OdooClient:
    cfg = OdooConfig(
        url=settings.ODOO_URL,
        db=settings.ODOO_DB,
        username=settings.ODOO_USER,
        password=getattr(settings, "ODOO_PASSWORD", getattr(settings, "ODOO_PASS", "")),
    )
    return OdooClient(cfg)

def _odoo_find_partner_id_by_doc(
    doc_digits: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
) -> int | None:
    """
    Procura SOMENTE (não cria, não atualiza) o partner no Odoo pelo documento.

    Regras:
    - 14 dígitos => CNPJ (campo l10n_br_cnpj)
    - 11 dígitos => CPF  (campo l10n_br_cpf)
    """
    doc = _only_digits(doc_digits or "")
    if len(doc) == 14:
        tipo = "l10n_br_cnpj"
    elif len(doc) == 11:
        tipo = "l10n_br_cpf"
    else:
        return None

    odoo = _odoo_client()
    return odoo.find_partner_by_doc(
        tipo_faturamento=tipo,
        doc=doc,
        email=email or None,
        phone=phone or None,
        name=name or None,
    )


def _normalize_cep(v: str) -> str:
    d = _only_digits(v or "")
    if len(d) == 8:
        return f"{d[:5]}-{d[5:]}"
    return (v or "").strip()


def _set_if_exists(obj, field: str, value):
    """Evita quebrar se seu model Venda não tiver algum campo."""
    if hasattr(obj, field):
        setattr(obj, field, value)

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("pedido")
@require_http_methods(["GET"])
def index(request: HttpRequest) -> HttpResponse:
    """
    Tela principal.
    - Mostra campo de busca (CPF/CNPJ/Nome).
    - Autopreenchimento via fetch em /pedido/api/lookup/
    - (Opcional) lista de registros via /pedido/api/buscar-registros/
    """
    return render(request, "pedido/index.html")


# =========================================================
# API: buscar registros (lista / autocomplete / histórico)
# =========================================================
@require_GET
def api_buscar_registros(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Sessão expirada. Faça login novamente."}, status=401)
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"ok": True, "q": "", "items": []})

    digits = _only_digits(q)
    qs = _registro_qs_do_usuario(request)

    registro_ids_bloqueados = list(_registro_ids_com_venda_bloqueada())
    if registro_ids_bloqueados:
        qs = qs.exclude(id__in=registro_ids_bloqueados)

    if digits:
        qs = qs.filter(documento=digits)
    else:
        qs = qs.filter(nome_cliente__icontains=q)

    qs = qs.order_by("-criado_em")[:50]

    items = []
    for r in qs:
        items.append(
            {
                "id": r.id,
                "nome_cliente": getattr(r, "nome_cliente", "") or "",
                "tipo_documento": getattr(r, "tipo_documento", "") or "",
                "documento": getattr(r, "documento", "") or "",
                "nome_vendedor": getattr(r, "nome_vendedor", "") or "",
                "localizacao": getattr(r, "localizacao", "") or "",
                "forma_pagamento": getattr(r, "forma_pagamento", "") or "",
                "quantidade_parcelas": getattr(r, "quantidade_parcelas", None),
                "equipamentos_resumo": getattr(r, "equipamentos_resumo", "") or "",
                "observacoes": getattr(r, "observacoes", "") or "",
                "criado_em": r.criado_em.isoformat() if getattr(r, "criado_em", None) else None,
            }
        )

    return JsonResponse({"ok": True, "q": q, "digits": digits, "items": items})


# =========================================================
# API: lookup cliente + registros do usuário
# =========================================================
@require_GET
def lookup_cliente_e_registro(request: HttpRequest) -> JsonResponse:
    """
    GET /pedido/api/lookup/?query=...
    Retorna:
    - cliente (cadastro real)
    - registros (lista de orçamentos do usuário logado para esse cliente)
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Sessão expirada. Faça login novamente."}, status=401)
    query = (request.GET.get("query") or "").strip()
    if not query:
        return JsonResponse({"ok": False, "message": "Informe CPF/CNPJ ou nome."}, status=400)

    digits = _only_digits(query)

    cliente = None

    # =========================
    # 1) tenta achar cliente direto por documento ou nome
    # =========================
    if len(digits) == 11:
        cliente = Cliente.objects.filter(cpf=digits).first()
    elif len(digits) == 14:
        cliente = Cliente.objects.filter(cnpj=digits).first()

    if not digits and not cliente:
        cliente = Cliente.objects.filter(nome__icontains=query).order_by("-atualizado_em").first()

    # =========================
    # 2) docs alvo (CPF/CNPJ)
    # - se o usuário digitou documento, usa ele
    # - se buscou por nome, usa CPF e CNPJ do cliente (prioriza CPF)
    # =========================
    docs_alvo: list[str] = []

    if len(digits) in (11, 14):
        docs_alvo = [digits]
    elif cliente:
        cpf = _only_digits(getattr(cliente, "cpf", "") or "")
        cnpj = _only_digits(getattr(cliente, "cnpj", "") or "")

        # ✅ PRIORIZA CPF (porque CNPJ pode estar lixo/placeholder)
        if len(cpf) == 11:
            docs_alvo.append(cpf)
        if len(cnpj) == 14:
            docs_alvo.append(cnpj)

    # =========================
    # 3) lista registros (✅ só do usuário)
    # =========================
    registros_qs = _registro_qs_do_usuario(request)

    if docs_alvo:
        registros_qs = registros_qs.filter(documento__in=docs_alvo)
    else:
        registros_qs = registros_qs.filter(nome_cliente__icontains=query)

    # =========================
    # 3.5) fallback do cliente via DOCUMENTO do registro (nome pode ter mudado)
    # =========================
    if not cliente:
        r0 = registros_qs.order_by("-criado_em").first()
        if r0:
            doc_r0 = _only_digits(getattr(r0, "documento", "") or "")
            tipo_r0 = (getattr(r0, "tipo_documento", "") or "").upper().strip()

            if len(doc_r0) == 11:
                cliente = Cliente.objects.filter(cpf=doc_r0).first()
            elif len(doc_r0) == 14:
                cliente = Cliente.objects.filter(cnpj=doc_r0).first()
            else:
                if tipo_r0 == "CPF":
                    cliente = Cliente.objects.filter(cpf=doc_r0).first()
                elif tipo_r0 == "CNPJ":
                    cliente = Cliente.objects.filter(cnpj=doc_r0).first()

            # se achou cliente agora, ajusta doc_alvo
            if cliente:
                docs_alvo = []
                cpf = _only_digits(getattr(cliente, "cpf", "") or "")
                cnpj = _only_digits(getattr(cliente, "cnpj", "") or "")
                if len(cpf) == 11:
                    docs_alvo.append(cpf)
                if len(cnpj) == 14:
                    docs_alvo.append(cnpj)

    # se doc_alvo foi ajustado pelo fallback, refiltra registros pelo doc (pra ficar consistente)
    if docs_alvo:
        registros_qs = _registro_qs_do_usuario(request).filter(documento__in=docs_alvo)
    else:
        registros_qs = _registro_qs_do_usuario(request).filter(nome_cliente__icontains=query)

    registro_ids_bloqueados = list(_registro_ids_com_venda_bloqueada())
    if registro_ids_bloqueados:
        registros_qs = registros_qs.exclude(id__in=registro_ids_bloqueados)

    registros_qs = registros_qs.order_by("-criado_em")[:50]

    registros = []
    vendas_por_registro = {
        v.registro_origem_id: v
        for v in Venda.objects.filter(registro_origem_id__in=[r.id for r in registros_qs])
    }
    for r in registros_qs:
        venda_rel = vendas_por_registro.get(r.id)

        registros.append(
            {
                "id": r.id,
                "nome_vendedor": getattr(r, "nome_vendedor", "") or "",
                "nome_cliente": getattr(r, "nome_cliente", "") or "",
                "tipo_documento": getattr(r, "tipo_documento", "") or "",
                "documento": getattr(r, "documento", "") or "",
                "localizacao": getattr(r, "localizacao", "") or "",
                "forma_pagamento": getattr(r, "forma_pagamento", "") or "",
                "quantidade_parcelas": getattr(r, "quantidade_parcelas", None),
                "equipamentos_resumo": getattr(r, "equipamentos_resumo", "") or "",
                "equipamentos_json": getattr(r, "equipamentos_json", None),
                "observacoes": getattr(r, "observacoes", "") or "",
                "criado_em": r.criado_em.isoformat() if getattr(r, "criado_em", None) else None,
                "entrada": str(getattr(r, "valor_entrada", getattr(r, "entrada", 0))),
                "desconto": str(getattr(r, "valor_desconto", getattr(r, "desconto", 0))),
                "frete": str(getattr(r, "valor_frete", getattr(r, "frete", 0))),
                "venda_id": getattr(venda_rel, "id", None),
                "link_pagamento": getattr(venda_rel, "link_pagamento", None),
                "token_pagamento": getattr(venda_rel, "token_pagamento", None),
                "odoo_sale_order_id": getattr(venda_rel, "odoo_sale_order_id", None),
                "status_venda": getattr(venda_rel, "status", None),
                "status_pagamento": getattr(venda_rel, "status_pagamento", None),
            }
        )

    payload = {
        "ok": True,
        "cliente": None,
        "registros": registros,
        "enderecos": [],
        "meta": {
            "query": query,
            "digits": digits,
            "found_cliente": bool(cliente),
            "registros_count": len(registros),
        },
    }

    if cliente:
        payload["cliente"] = {
            "id": cliente.id,
            "nome": getattr(cliente, "nome", "") or "",
            "profissao": getattr(cliente, "profissao", "") or "",
            "cpf": getattr(cliente, "cpf", "") or "",
            "cnpj": getattr(cliente, "cnpj", "") or "",
            "email": getattr(cliente, "email", "") or "",
            "telefone": getattr(cliente, "telefone", "") or "",
            "observacoes": getattr(cliente, "observacoes", "") or "",
            "endereco": getattr(cliente, "endereco", "") or "",
            "numero": getattr(cliente, "numero", "") or "",
            "complemento": getattr(cliente, "complemento", "") or "",
            "bairro": getattr(cliente, "bairro", "") or "",
            "cidade": getattr(cliente, "cidade", "") or "",
            "uf": getattr(cliente, "uf", "") or "",
            "cep": getattr(cliente, "cep", "") or "",
            "localizacao": getattr(cliente, "localizacao", "") or "",
            "inscricao_estadual": getattr(cliente, "inscricao_estadual", "") or "",
        }

        # endereços adicionais (para entrega)
        end_qs = ClienteEndereco.objects.filter(cliente=cliente, is_ativo=True).order_by(
            "-is_padrao_entrega", "-atualizado_em", "id"
        )
        payload["enderecos"] = [
            {
                "id": e.id,
                "nome": e.nome,
                "is_padrao_entrega": bool(getattr(e, "is_padrao_entrega", False)),
                "endereco": e.endereco or "",
                "numero": e.numero or "",
                "complemento": e.complemento or "",
                "bairro": e.bairro or "",
                "cidade": e.cidade or "",
                "uf": e.uf or "",
                "cep": e.cep or "",
                "formatado": getattr(e, "endereco_formatado", "") or "",
            }
            for e in end_qs
        ]

    return JsonResponse(payload, status=200)


@require_http_methods(["POST"])
@transaction.atomic
def api_salvar_cliente(request: HttpRequest, cliente_id: int) -> JsonResponse:
    """
    POST /pedido/api/cliente/<id>/salvar/
    Body JSON: { nome, email, telefone, profissao, cpf, cnpj, localizacao, endereco, numero, complemento,
                 bairro, cidade, uf, cep, observacoes, inscricao_estadual }
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Não autenticado."}, status=401)

    cliente = get_object_or_404(Cliente, pk=cliente_id)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "message": "JSON inválido."}, status=400)

    def s(k):  # string safe
        return (data.get(k) or "").strip()

    def d(k):  # only digits
        return _only_digits(s(k))

    for field, value in [
        ("nome", s("nome")),
        ("email", s("email")),
        ("telefone", s("telefone")),
        ("profissao", s("profissao")),
        ("cpf", d("cpf")),
        ("cnpj", d("cnpj")),
        ("inscricao_estadual", s("inscricao_estadual")),
        ("endereco", s("endereco")),
        ("numero", s("numero")),
        ("complemento", s("complemento")),
        ("bairro", s("bairro")),
        ("cidade", s("cidade")),
        ("uf", s("uf")),
        ("cep", d("cep")),
        ("observacoes", s("observacoes")),
    ]:
        if hasattr(cliente, field):
            setattr(cliente, field, value)

    cliente.save()

    return JsonResponse(
        {
            "ok": True,
            "message": "Cliente salvo com sucesso.",
            "cliente": {
                "id": cliente.id,
                "nome": getattr(cliente, "nome", "") or "",
                "email": getattr(cliente, "email", "") or "",
                "telefone": getattr(cliente, "telefone", "") or "",
                "profissao": getattr(cliente, "profissao", "") or "",
                "cpf": getattr(cliente, "cpf", "") or "",
                "cnpj": getattr(cliente, "cnpj", "") or "",
                "localizacao": getattr(cliente, "localizacao", "") or "",
                "endereco": getattr(cliente, "endereco", "") or "",
                "numero": getattr(cliente, "numero", "") or "",
                "complemento": getattr(cliente, "complemento", "") or "",
                "bairro": getattr(cliente, "bairro", "") or "",
                "cidade": getattr(cliente, "cidade", "") or "",
                "uf": getattr(cliente, "uf", "") or "",
                "cep": getattr(cliente, "cep", "") or "",
                "observacoes": getattr(cliente, "observacoes", "") or "",
                "inscricao_estadual": getattr(cliente, "inscricao_estadual", "") or "",
            },
        }
    )


# =========================================================
# API: endereços do cliente (lista + criar)
# =========================================================
@require_GET
def api_listar_enderecos_cliente(request: HttpRequest, cliente_id: int) -> JsonResponse:
    """
    GET /pedido/api/cliente/<id>/enderecos/
    Retorna endereços ativos do cliente (para seleção na entrega).
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Não autenticado."}, status=401)

    cliente = get_object_or_404(Cliente, pk=cliente_id)

    qs = ClienteEndereco.objects.filter(cliente=cliente, is_ativo=True).order_by(
        "-is_padrao_entrega", "-atualizado_em", "id"
    )

    items = [
        {
            "id": e.id,
            "nome": e.nome,
            "is_padrao_entrega": bool(getattr(e, "is_padrao_entrega", False)),
            "endereco": e.endereco or "",
            "numero": e.numero or "",
            "complemento": e.complemento or "",
            "bairro": e.bairro or "",
            "cidade": e.cidade or "",
            "uf": e.uf or "",
            "cep": e.cep or "",
            "formatado": getattr(e, "endereco_formatado", "") or "",
        }
        for e in qs
    ]

    return JsonResponse({"ok": True, "cliente_id": cliente.id, "items": items})


@require_http_methods(["POST"])
@transaction.atomic
def api_salvar_endereco_cliente(request: HttpRequest, cliente_id: int) -> JsonResponse:
    """
    POST /pedido/api/cliente/<id>/enderecos/salvar/
    Body JSON:
      {
        "nome": "Casa",
        "endereco": "...",
        "numero": "...",
        "complemento": "...",
        "bairro": "...",
        "cidade": "...",
        "uf": "SP",
        "cep": "00000-000",
        "is_padrao_entrega": true/false
      }

    Regra:
    - Se já existir um endereço do cliente com os mesmos campos, retorna o existente.
    - Se não existir, cria e retorna.
    - Se o cliente já tiver odoo_partner_id, tenta sincronizar esse endereço no Odoo
      como um res.partner filho do cliente principal.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "message": "Não autenticado."}, status=401)

    cliente = get_object_or_404(Cliente, pk=cliente_id)

    try:
        data = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        return JsonResponse({"ok": False, "message": "JSON inválido."}, status=400)

    def s(k):
        return (data.get(k) or "").strip()

    nome = s("nome") or "Endereço"
    endereco = s("endereco")
    numero = s("numero")
    complemento = s("complemento")
    bairro = s("bairro")
    cidade = s("cidade")
    uf = (s("uf") or "").upper()[:2]
    cep = _normalize_cep(s("cep"))
    is_padrao = bool(data.get("is_padrao_entrega") or False)

    has_any = any(
        [
            (endereco or "").strip(),
            (bairro or "").strip(),
            (cidade or "").strip(),
            (uf or "").strip(),
            _only_digits(cep),
        ]
    )
    if not has_any:
        return JsonResponse(
            {"ok": False, "message": "Preencha pelo menos Endereço/Cidade/UF/CEP."},
            status=400,
        )

    existente = ClienteEndereco.objects.filter(
        cliente=cliente,
        endereco__iexact=endereco.strip(),
        numero__iexact=numero.strip() if numero else "",
        complemento__iexact=complemento.strip() if complemento else "",
        bairro__iexact=bairro.strip() if bairro else "",
        cidade__iexact=cidade.strip() if cidade else "",
        uf__iexact=uf.strip() if uf else "",
        cep__iexact=cep,
    ).order_by("-atualizado_em", "-id").first()

    if existente:
        if is_padrao and not getattr(existente, "is_padrao_entrega", False):
            existente.is_padrao_entrega = True
            existente.save(update_fields=["is_padrao_entrega", "atualizado_em"])

        return JsonResponse(
            {
                "ok": True,
                "created": False,
                "message": "Endereço já existia. Usando o existente.",
                "endereco": {
                    "id": existente.id,
                    "nome": existente.nome,
                    "is_padrao_entrega": bool(getattr(existente, "is_padrao_entrega", False)),
                    "formatado": getattr(existente, "endereco_formatado", "") or "",
                    "odoo_endereco_partner_id": getattr(existente, "odoo_endereco_partner_id", None),
                },
            }
        )

    novo = ClienteEndereco.objects.create(
        cliente=cliente,
        nome=nome,
        is_ativo=True,
        is_padrao_entrega=is_padrao,
        endereco=endereco,
        numero=numero,
        complemento=complemento,
        bairro=bairro,
        cidade=cidade,
        uf=uf,
        cep=cep,
    )

    odoo_endereco_id = None

    try:
        odoo_partner_id = getattr(cliente, "odoo_partner_id", None)

        logger.warning("====================================")
        logger.warning("SYNC ENDEREÇO ENTREGA ODOO")
        logger.warning("cliente_id: %s", cliente.id)
        logger.warning("cliente.odoo_partner_id: %s", odoo_partner_id)
        logger.warning("novo_endereco_id: %s", novo.id)
        logger.warning("====================================")

        if odoo_partner_id:
            odoo = _odoo_client()

            existente_odoo_id = odoo.buscar_endereco_entrega_existente(
                parent_id=int(odoo_partner_id),
                endereco=endereco,
                numero=numero,
                bairro=bairro,
                cep=cep,
            )

            if existente_odoo_id:
                odoo_endereco_id = int(existente_odoo_id)
                logger.warning("ENDEREÇO DE ENTREGA JÁ EXISTIA NO ODOO")
                logger.warning("odoo_endereco_id: %s", odoo_endereco_id)
            else:
                odoo_endereco_id = odoo.criar_endereco_entrega_partner(
                    parent_id=int(odoo_partner_id),
                    nome=nome,
                    endereco=endereco,
                    numero=numero,
                    complemento=complemento,
                    bairro=bairro,
                    cidade_nome=cidade,
                    uf=uf,
                    cep=cep,
                )
                logger.warning("ENDEREÇO DE ENTREGA CRIADO NO ODOO")
                logger.warning("odoo_endereco_id: %s", odoo_endereco_id)

            # salva no model local, no campo CERTO
            if hasattr(novo, "odoo_endereco_partner_id"):
                novo.odoo_endereco_partner_id = odoo_endereco_id
                try:
                    novo.save(update_fields=["odoo_endereco_partner_id", "atualizado_em"])
                    logger.warning("odoo_endereco_partner_id salvo no ClienteEndereco: %s", odoo_endereco_id)
                except Exception as e:
                    logger.warning("Erro ao salvar odoo_endereco_partner_id no ClienteEndereco: %s", e)
        else:
            logger.warning("CLIENTE AINDA NÃO TEM odoo_partner_id, endereço salvo só localmente")

    except Exception as e:
        logger.warning("ERRO AO SINCRONIZAR ENDEREÇO DE ENTREGA NO ODOO")
        logger.warning("Erro: %s", str(e))

    return JsonResponse(
        {
            "ok": True,
            "created": True,
            "message": "Endereço salvo com sucesso.",
            "endereco": {
                "id": novo.id,
                "nome": novo.nome,
                "is_padrao_entrega": bool(getattr(novo, "is_padrao_entrega", False)),
                "formatado": getattr(novo, "endereco_formatado", "") or "",
                "odoo_endereco_partner_id": odoo_endereco_id,
            },
        }
    )
def _explodir_itens_registro_para_linhas_odoo(registro: Registro) -> list[dict]:
    """
    Usa:
    - equipamentos_json => origem do preço e quantidade
    - traduzir_resumo_de_produtos() => origem da explosão dos componentes

    Regra:
    - item simples => 1 linha com preço normal
    - item com múltiplos produtos => divide o valor igualmente entre todos
    - sem tratamento especial para brinde
    - ajuste de centavos vai para a última linha
    """
    equip_json = getattr(registro, "equipamentos_json", []) or []
    linhas = []

    for item in equip_json:
        nome_item = (item.get("nome") or "").strip()
        logger.warning("Processando item: %s", nome_item)
        qtd = int(item.get("quantidade") or 1)
        price_unit_total = float(item.get("valor_unitario") or 0)

        if not nome_item:
            continue

        resumo_fake = f"{nome_item} ({qtd}x)"
        partes = traduzir_resumo_de_produtos(resumo_fake)
        logger.warning("Partes traduzidas: %s", partes)
        # Se não conseguir fatiar, mantém como item único
        if not partes:
            linhas.append({
                "nome_busca": nome_item,
                "qtd": qtd,
                "price_unit": round(price_unit_total, 2),
            })
            continue

        # Remove entradas sem nome
        partes_processadas = []
        for parte in partes:
            nome_busca = (parte.get("nome_busca") or "").strip()
            logger.warning("Parte processada: %s, qtd: %s", nome_busca, parte.get("qtd"))
            if not nome_busca:
                continue

            partes_processadas.append({
                "nome_busca": nome_busca,
                "qtd": int(parte.get("qtd") or qtd),
            })

        if not partes_processadas:
            continue

        # Se só tem uma parte, mantém preço inteiro
        if len(partes_processadas) == 1:
            linhas.append({
                "nome_busca": partes_processadas[0]["nome_busca"],
                "qtd": partes_processadas[0]["qtd"],
                "price_unit": round(price_unit_total, 2),
            })
            continue

        # Divide igualmente entre todos
        total_centavos = int(round(price_unit_total * 100))
        qtd_partes = len(partes_processadas)

        base_centavos = total_centavos // qtd_partes
        resto_centavos = total_centavos - (base_centavos * qtd_partes)

        for i, parte in enumerate(partes_processadas):
            valor_centavos = base_centavos
            if i == qtd_partes - 1:
                valor_centavos += resto_centavos

            linhas.append({
                "nome_busca": parte["nome_busca"],
                "qtd": parte["qtd"],
                "price_unit": round(valor_centavos / 100.0, 2),
            })
    logger.warning("Linhas explodidas para odoo: %s", linhas)
    return linhas

# =========================================================
# Abrir registro -> cria/abre Venda
# =========================================================
@login_required(login_url=settings.URL_LOGIN)    
@require_http_methods(["POST"])
@transaction.atomic
@require_system_access("pedido")
def abrir_registro_no_painel(request: HttpRequest, registro_id: int) -> HttpResponse:

    def _to_float(value, default=0.0):
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return default
        s = re.sub(r"[^\d,.\-]", "", s)
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            return float(s)
        except Exception:
            return default

    def _safe_strip(value):
        if isinstance(value, list):
            value = " | ".join(str(x) for x in value if x)
        return str(value or "").strip()

    def _calcular_total_equipamentos(registro) -> float:
        equipamentos = getattr(registro, "equipamentos_json", None) or []
        total = 0.0

        for item in equipamentos:
            qtd = int(item.get("quantidade") or 1)
            valor_unit = _to_float(item.get("valor_unitario"), 0.0)
            total += qtd * valor_unit

        return round(total, 2)

    registro = get_object_or_404(Registro, pk=registro_id)

    logger.warning("===================================")
    logger.warning("DEBUG ABRIR REGISTRO")
    logger.warning("registro_id recebido: %s", registro_id)
    logger.warning("registro.pk: %s", getattr(registro, "pk", None))
    logger.warning("registro.criado_em: %s", getattr(registro, "criado_em", None))
    logger.warning("===================================")

    if not _registro_qs_do_usuario(request).filter(pk=registro_id).exists():
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"ok": False, "message": "Você não tem permissão para abrir este orçamento."},
                status=403,
            )
        messages.error(request, "Você não tem permissão para abrir este orçamento.")
        return redirect("pedido:index")

    # =========================================================
    # 1) Busca ou cria a venda local
    # =========================================================
    old_venda_id = request.POST.get("old_venda_id")
    venda = None

    if old_venda_id:
        venda = Venda.objects.filter(pk=old_venda_id).first()
        if venda:
            venda.registro_origem = registro
            venda.save(update_fields=["registro_origem"])
            logger.warning("===================================")
            logger.warning("REAPROVEITANDO VENDA ANTIGA PARA ATUALIZAR ODOO: %s", venda.id)
            logger.warning("===================================")

    logger.warning("===================================")
    logger.warning("DEBUG VENDA LOCAL")
    logger.warning("venda encontrada por registro_origem: %s", getattr(venda, "id", None))
    logger.warning(
        "venda.odoo_sale_order_id: %s",
        getattr(venda, "odoo_sale_order_id", None) if venda else None,
    )
    logger.warning("===================================")

    doc = _only_digits(getattr(registro, "documento", "") or "")
    cliente_local = None
    if len(doc) == 11:
        cliente_local = Cliente.objects.filter(cpf=doc).first()
    elif len(doc) == 14:
        cliente_local = Cliente.objects.filter(cnpj=doc).first()

    if not venda:
        venda = Venda(
            registro_origem=registro,
            vendedor=request.user,
            nome_cliente=getattr(registro, "nome_cliente", "") or "",
            tipo_documento=getattr(registro, "tipo_documento", "") or "",
            documento=getattr(registro, "documento", "") or "",
            localizacao=getattr(registro, "localizacao", "") or "",
            forma_pagamento=getattr(registro, "forma_pagamento", "") or "",
            status=Venda.StatusChoices.ORCAMENTO,
        )

        _set_if_exists(venda, "observacoes", getattr(registro, "observacoes", "") or "")
        _set_if_exists(venda, "equipamentos_resumo", getattr(registro, "equipamentos_resumo", "") or "")
        _set_if_exists(venda, "equipamentos_json", getattr(registro, "equipamentos_json", None))

        quantidade_parcelas_inicial = getattr(registro, "quantidade_parcelas", None)
        try:
            quantidade_parcelas_inicial = int(quantidade_parcelas_inicial or 1)
        except (TypeError, ValueError):
            quantidade_parcelas_inicial = 1
        _set_if_exists(venda, "quantidade_parcelas", quantidade_parcelas_inicial)

        if cliente_local and hasattr(venda, "cliente"):
            venda.cliente = cliente_local

        venda.save()

    # =========================================================
    # 2) Sincroniza dados locais da venda com o registro
    # =========================================================
    valor_total_registro = _to_float(
        getattr(registro, "valor_total", None)
        or getattr(registro, "total", None)
        or getattr(registro, "valor_final", None)
        or getattr(registro, "valor_avista", None)
        or getattr(registro, "avista_total", None)
        or getattr(registro, "valor_total_avista", None),
        0.0,
    )

    if valor_total_registro <= 0:
        valor_total_registro = _calcular_total_equipamentos(registro)

    valor_frete = _to_float(getattr(registro, "valor_frete", getattr(registro, "frete", 0)), 0.0)
    valor_desconto = _to_float(getattr(registro, "valor_desconto", getattr(registro, "desconto", 0)), 0.0)
    valor_total_registro = round(valor_total_registro + valor_frete - valor_desconto, 2)
    if valor_total_registro < 0:
        valor_total_registro = 0.0

    campos_sync = []

    mapa_sync = {
        "nome_cliente": getattr(registro, "nome_cliente", "") or "",
        "tipo_documento": getattr(registro, "tipo_documento", "") or "",
        "documento": getattr(registro, "documento", "") or "",
        "localizacao": getattr(registro, "localizacao", "") or "",
        "forma_pagamento": getattr(registro, "forma_pagamento", "") or "",
        "observacoes": getattr(registro, "observacoes", "") or "",
        "equipamentos_resumo": getattr(registro, "equipamentos_resumo", "") or "",
        "equipamentos_json": getattr(registro, "equipamentos_json", None),
    }

    for campo, novo_valor in mapa_sync.items():
        if hasattr(venda, campo) and getattr(venda, campo) != novo_valor:
            setattr(venda, campo, novo_valor)
            campos_sync.append(campo)

    if hasattr(venda, "quantidade_parcelas"):
        novo = getattr(registro, "quantidade_parcelas", None)
        try:
            novo = int(novo or 1)
        except (TypeError, ValueError):
            novo = 1

        if getattr(venda, "quantidade_parcelas", None) != novo:
            venda.quantidade_parcelas = novo
            campos_sync.append("quantidade_parcelas")

    for campo_valor in ["valor_total", "valor_final", "valor", "total"]:
        if hasattr(venda, campo_valor) and getattr(venda, campo_valor) != valor_total_registro:
            setattr(venda, campo_valor, valor_total_registro)
            campos_sync.append(campo_valor)

    if hasattr(venda, "valor_avista"):
        valor_avista_sync = _to_float(getattr(registro, "valor_avista", 0), 0.0) or valor_total_registro
        if getattr(venda, "valor_avista", None) != valor_avista_sync:
            venda.valor_avista = valor_avista_sync
            campos_sync.append("valor_avista")

    if campos_sync:
        venda.save(update_fields=list(dict.fromkeys(campos_sync)))

    # =========================================================
    # Variáveis de controle do retorno
    # =========================================================
    odoo = None
    link_pagamento = getattr(venda, "link_pagamento", None)
    resultado_parcelas = {
        "ok": False,
        "message": None,
    }
    pedido_criado = False
    pedido_confirmado = False
    mensagem_final = "Venda criada com sucesso."

    # =========================================================
    # 3) Resolve cliente / partner no Odoo
    # =========================================================
    try:
        odoo = _odoo_client()

        if getattr(venda, "odoo_partner_id", None) is None:
            email = getattr(cliente_local, "email", "") if cliente_local else None
            phone = getattr(cliente_local, "telefone", "") if cliente_local else None
            name = getattr(cliente_local, "nome", "") if cliente_local else getattr(registro, "nome_cliente", "")
            if not name:
                name = "Cliente Sem Nome"

            tipo = "l10n_br_cnpj" if len(doc) == 14 else "l10n_br_cpf"
            company_type = "company" if len(doc) == 14 else "person"

            partner_id = odoo.find_partner_by_doc(
                tipo_faturamento=tipo,
                doc=doc,
                email=email or None,
                phone=phone or None,
                name=name,
            )

            if not partner_id:
                if len(doc) == 11:
                    doc_formatado = f"{doc[:3]}.{doc[3:6]}.{doc[6:9]}-{doc[9:]}"
                    indicador_ie = "9"
                    is_company = False
                else:
                    doc_formatado = f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}"
                    indicador_ie = False
                    is_company = True

                cli_endereco = getattr(cliente_local, "endereco", "") if cliente_local else ""
                cli_numero = getattr(cliente_local, "numero", "") if cliente_local else ""
                cli_complemento = getattr(cliente_local, "complemento", "") if cliente_local else ""
                cli_bairro = getattr(cliente_local, "bairro", "") if cliente_local else ""
                cli_cidade = getattr(cliente_local, "cidade", "") if cliente_local else ""
                cli_uf = getattr(cliente_local, "uf", "") if cliente_local else ""
                cli_cep = getattr(cliente_local, "cep", "") if cliente_local else ""

                country_id, state_id, city_id = odoo.buscar_ids_endereco(cli_uf, cli_cidade)

                vals_partner = {
                    "name": name,
                    "email": email or False,
                    "phone": phone or False,
                    "mobile": phone or False,
                    "company_type": company_type,
                    "is_company": is_company,
                    "l10n_br_indicador_ie": indicador_ie,
                    tipo: doc_formatado,
                    "zip": _only_digits(cli_cep) if cli_cep else False,
                    "street": cli_endereco or False,
                    "l10n_br_endereco_numero": cli_numero or False,
                    "street2": cli_complemento or False,
                    "l10n_br_endereco_bairro": cli_bairro or False,
                }

                if country_id:
                    vals_partner["country_id"] = country_id
                if state_id:
                    vals_partner["state_id"] = state_id
                if city_id:
                    vals_partner["l10n_br_municipio_id"] = city_id

                partner_id = odoo.partner_create(vals_partner)

                vals_pos_create = {}
                if country_id:
                    vals_pos_create["country_id"] = country_id
                if state_id:
                    vals_pos_create["state_id"] = state_id
                if city_id:
                    vals_pos_create["l10n_br_municipio_id"] = city_id

                if vals_pos_create:
                    try:
                        odoo.partner_write(partner_id, vals_pos_create)
                    except Exception:
                        pass

            if partner_id:
                _set_if_exists(venda, "odoo_partner_id", partner_id)
                if hasattr(venda, "odoo_partner_id"):
                    venda.save(update_fields=["odoo_partner_id"])

                if cliente_local:
                    cliente_local.odoo_partner_id = partner_id
                    try:
                        cliente_local.save(update_fields=["odoo_partner_id"])
                    except Exception as e:
                        logger.warning("Erro ao salvar odoo_partner_id no cliente: %s", e)

                profissao_cliente = getattr(cliente_local, "profissao", "") if cliente_local else ""
                try:
                    _odoo_garantir_categoria_partner(
                        odoo=odoo,
                        partner_id=int(partner_id),
                        profissao=profissao_cliente,
                    )
                except Exception as e:
                    logger.warning("Erro ao garantir categoria do partner: %s", e)

    except Exception as e:
        logger.warning("ERRO AO RESOLVER PARTNER ODOO: %s", e)

    # =========================================================
    # 4) Resolve vendedor no Odoo
    # =========================================================
    vendedor_id = None

    try:
        if odoo is None:
            odoo = _odoo_client()

        perfil = (
            getattr(request.user, "profile", None)
            or getattr(request.user, "painelprofile", None)
        )

        nome_busca_vendedor = (getattr(registro, "nome_vendedor", "") or request.user.username or "").strip()

        vendedor_odoo = None

        if perfil and getattr(perfil, "odoo_user_id", None):
            vendedor_odoo = {
                "id": perfil.odoo_user_id,
                "name": nome_busca_vendedor,
                "login": "",
                "created": False,
            }
        elif nome_busca_vendedor:
            vendedor_odoo = odoo.buscar_vendedor(nome_busca_vendedor)
            if not vendedor_odoo:
                vendedor_odoo = odoo.criar_vendedor(nome_busca_vendedor)

        if vendedor_odoo and vendedor_odoo.get("id"):
            vendedor_id = int(vendedor_odoo["id"])

            if perfil and getattr(perfil, "odoo_user_id", None) != vendedor_id:
                try:
                    perfil.odoo_user_id = vendedor_id
                    perfil.save(update_fields=["odoo_user_id"])
                except Exception as e:
                    logger.warning("Erro ao salvar odoo_user_id no perfil: %s", e)

            campos_vendedor = []
            if hasattr(venda, "odoo_user_id"):
                venda.odoo_user_id = vendedor_id
                campos_vendedor.append("odoo_user_id")

            if hasattr(venda, "odoo_vendedor_id"):
                venda.odoo_vendedor_id = vendedor_id
                campos_vendedor.append("odoo_vendedor_id")

            if campos_vendedor:
                venda.save(update_fields=campos_vendedor)

    except Exception as e:
        logger.warning("ERRO AO RESOLVER VENDEDOR ODOO: %s", e)

    # =========================================================
    # 5) Monta dados da cotação / cria ou atualiza no Odoo
    # =========================================================
    try:
        if odoo is None:
            odoo = _odoo_client()

        partner_id = (
            getattr(venda, "odoo_partner_id", None)
            or getattr(cliente_local, "odoo_partner_id", None)
        )

        if not partner_id:
            raise Exception("Venda sem partner_id no Odoo.")

        perfil = (
            getattr(request.user, "profile", None)
            or getattr(request.user, "painelprofile", None)
        )

        vendedor_id = (
            getattr(venda, "odoo_user_id", None)
            or getattr(venda, "odoo_vendedor_id", None)
            or getattr(perfil, "odoo_user_id", None)
            or vendedor_id
        )

        partner_invoice_id = int(partner_id)
        partner_shipping_id = int(partner_id)

        forma_pagamento = (getattr(registro, "forma_pagamento", "") or "").strip().lower()

        eh_pix = forma_pagamento == "pix"
        eh_boleto = forma_pagamento == "boleto"
        eh_cartao = forma_pagamento in [
            "cartao",
            "cartão",
            "cartao de credito",
            "cartão de crédito",
        ]

        payment_provider_id = False
        valor_entrada = _to_float(getattr(registro, "valor_entrada", 0))
        numero_parcelas = int(getattr(registro, "quantidade_parcelas", 1) or 1)
        tem_entrada = valor_entrada > 0

        if eh_pix:
            provider = odoo.buscar_payment_provider("PIX")
            payment_provider_id = int(provider["id"]) if provider else False
            numero_parcelas = 1
        elif eh_cartao:
            provider = odoo.buscar_payment_provider("Cartão de Crédito")
            payment_provider_id = int(provider["id"]) if provider else False
            numero_parcelas = 1
        elif eh_boleto:
            provider = odoo.buscar_payment_provider("Boleto Itaú")
            payment_provider_id = int(provider["id"]) if provider else False

        valor_frete = _to_float(getattr(registro, "valor_frete", getattr(registro, "frete", 0)))
        valor_avista = _to_float(getattr(registro, "valor_avista", 0))

        vals_order = {
            "partner_id": int(partner_id),
            "partner_invoice_id": partner_invoice_id,
            "partner_shipping_id": partner_shipping_id,
            "user_id": int(vendedor_id) if vendedor_id else False,
            "l10n_br_operacao_consumidor": "1",
            "l10n_br_frete": valor_frete,
            "x_studio_valor_vista_1": valor_avista,
            "payment_provider_id": payment_provider_id or False,
            "incoterm": 6,
            "valor_entrada": valor_entrada,
            "numero_parcelas": numero_parcelas,
            "tipo_entrada": "fixo" if tem_entrada else "sem",
        }

        linhas_odoo = _explodir_itens_registro_para_linhas_odoo(registro)

        # =====================================================
        # 6) Cria ou atualiza cotação no Odoo
        # =====================================================
        venda_ja_existia_no_odoo = bool(getattr(venda, "odoo_sale_order_id", None))

        if venda_ja_existia_no_odoo:
            sale_order_id = int(venda.odoo_sale_order_id)
            logger.warning("ATUALIZANDO COTAÇÃO ODOO: %s", sale_order_id)

            odoo.sale_order_write(sale_order_id, vals_order)

            linhas_criacao = []
            for item in linhas_odoo:
                nome_busca = _safe_strip(item.get("nome_busca"))
                qtd = int(item.get("qtd") or 1)
                price_unit = _to_float(item.get("price_unit", 0))

                if not nome_busca or price_unit <= 0:
                    continue

                produto_odoo = odoo.buscar_produto(nome_busca)
                if not produto_odoo:
                    logger.warning("PRODUTO NÃO ENCONTRADO NO ODOO: %s", nome_busca)
                    continue

                linhas_criacao.append({
                    "product_id": int(produto_odoo["id"]),
                    "product_uom_qty": qtd,
                    "price_unit": price_unit,
                    "discount": 0.0,
                })

            odoo.sale_order_replace_lines(sale_order_id, linhas_criacao)

        else:
            logger.warning("CRIANDO COTAÇÃO ODOO")
            sale_order_id = odoo.sale_order_create(vals_order)

            if hasattr(venda, "odoo_sale_order_id"):
                venda.odoo_sale_order_id = sale_order_id
                venda.save(update_fields=["odoo_sale_order_id"])

            for item in linhas_odoo:
                nome_busca = _safe_strip(item.get("nome_busca"))
                qtd = int(item.get("qtd") or 1)
                price_unit = _to_float(item.get("price_unit", 0))

                if not nome_busca or price_unit <= 0:
                    continue

                produto_odoo = odoo.buscar_produto(nome_busca)
                if not produto_odoo:
                    logger.warning("PRODUTO NÃO ENCONTRADO NO ODOO: %s", nome_busca)
                    continue

                linha = {
                    "order_id": int(sale_order_id),
                    "product_id": int(produto_odoo["id"]),
                    "product_uom_qty": qtd,
                    "price_unit": price_unit,
                    "discount": 0.0,
                }

                odoo.sale_order_line_create(linha)

        pedido_criado = True

        # =====================================================
        # 7) Link de pagamento
        # =====================================================
        resultado_pagamento = _gerar_ou_reaproveitar_link_pagamento(
            request=request,
            venda=venda,
            forma_pagamento=getattr(registro, "forma_pagamento", "") or "",
        )

        if isinstance(resultado_pagamento, dict) and resultado_pagamento.get("tipo") == "odoo":
            return JsonResponse(resultado_pagamento)

        if isinstance(resultado_pagamento, str) and resultado_pagamento.strip():
            link_pagamento = resultado_pagamento.strip()
        else:
            link_pagamento = getattr(venda, "link_pagamento", None)

        if link_pagamento and hasattr(venda, "link_pagamento") and venda.link_pagamento != link_pagamento:
            venda.link_pagamento = link_pagamento
            venda.save(update_fields=["link_pagamento"])

        logger.warning("LINK PAGAMENTO FINAL: %s", link_pagamento)

        # =====================================================
        # 8) Aprovação comercial
        # =====================================================
        if eh_cartao or eh_pix:
            try:
                resultado_aprovacao = _agendar_aprovacao_comercial_no_odoo(venda)
                logger.warning("RESULTADO ATIVIDADE APROVAÇÃO: %s", resultado_aprovacao)
            except Exception as e:
                logger.warning("ERRO AO AGENDAR APROVAÇÃO: %s", e)

        # =====================================================
        # 9) Parcelas para boleto
        # =====================================================
        if eh_boleto:
            try:
                retorno_odoo = odoo.sale_order_call_method(
                    int(sale_order_id),
                    "gerar_parcelas",
                )

                logger.warning("GERAR PARCELAS EXECUTADO: %s", retorno_odoo)

                resultado_parcelas = {
                    "ok": True,
                    "message": "Parcelas geradas no Odoo com sucesso.",
                    "raw": retorno_odoo,
                }
            except Exception as e:
                logger.warning("ERRO AO EXECUTAR GERAR PARCELAS: %s", e)
                resultado_parcelas = {
                    "ok": False,
                    "message": f"Venda criada no Odoo, mas houve erro ao gerar parcelas: {e}",
                }

        # =====================================================
        # 10) Nota interna
        # =====================================================
        try:
            obs = (getattr(registro, "observacoes", "") or "").strip()
            if obs:
                odoo.adicionar_nota_pedido(int(sale_order_id), obs)
        except Exception as e:
            logger.warning("ERRO AO SALVAR NOTA INTERNA: %s", e)

        # =====================================================
        # 11) Anexos no Odoo
        # =====================================================
        DOC_LABELS = {
            "doc_contrato": "CONTRATO SOCIAL / CCMEI / DOCUMENTO PESSOAL (PF)",
            "doc_cnpj": "COMPROVANTE DE INSCRIÇÃO E SITUAÇÃO CADASTRAL DO CNPJ",
            "doc_titular": "DOCUMENTO DO TITULAR (RG/CPF OU CNH)",
            "doc_residencia": "COMPROVANTE DE ENDEREÇO DE FATURAMENTO",
            "doc_endereco_entrega": "COMPROVANTE DE ENDEREÇO DE ENTREGA",
            "doc_pagamento": "COMPROVANTE DE PAGAMENTO",
            "doc_pagamento_entrada": "COMPROVANTE DE PAGAMENTO (ENTRADA)",
            "doc_antifraude": "CARTA ANTI-FRAUDE",
            "doc_selfie": "SELFIE COM DOCUMENTO DE IDENTIFICAÇÃO",
            "doc_serial": "FOTO DO SERIAL DO EQUIPAMENTO",
        }

        try:
            logger.warning("===================================")
            logger.warning("INICIANDO ENVIO DE ANEXOS PARA O ODOO")
            logger.warning("sale_order_id: %s", sale_order_id)
            logger.warning("arquivos recebidos: %s", list(request.FILES.keys()))
            logger.warning("===================================")

            for field_name in request.FILES:
                arquivos = request.FILES.getlist(field_name)

                for arquivo in arquivos:
                    label = DOC_LABELS.get(field_name, field_name)
                    texto_chatter = f"{label} - Documento enviado pelo painel"
                    nome_arquivo = arquivo.name
                    conteudo = arquivo.read()
                    mimetype = getattr(arquivo, "content_type", None)

                    attachment_id = odoo.anexar_arquivo_em_sale_order(
                        sale_order_id=int(sale_order_id),
                        nome_arquivo=nome_arquivo,
                        conteudo=conteudo,
                        mimetype=mimetype,
                    )
                    odoo.postar_anexo_no_chatter(
                        int(sale_order_id),
                        attachment_id,
                        body=texto_chatter,
                    )

                    logger.warning("ANEXO ENVIADO COM SUCESSO")
                    logger.warning("field_name: %s", field_name)
                    logger.warning("nome_arquivo: %s", nome_arquivo)
                    logger.warning("attachment_id: %s", attachment_id)

        except Exception as e:
            logger.exception("ERRO AO ENVIAR ANEXOS PARA O ODOO: %s", e)

    except Exception as e:
        logger.exception("ERRO AO CRIAR/ATUALIZAR COTAÇÃO ODOO: %s", e)
        mensagem_final = f"Falha ao criar venda: {e}"

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {
                    "ok": False,
                    "message": mensagem_final,
                },
                status=500,
            )

        messages.error(request, mensagem_final)
        return redirect("pedido:index")

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        try:
            payload = {
                "ok": True,
                "message": mensagem_final,
                "venda_id": int(venda.id) if venda.id is not None else None,
                "odoo_sale_order_id": int(venda.odoo_sale_order_id) if venda.odoo_sale_order_id else None,
                "status": str(venda.status or ""),
                "status_pagamento": str(venda.status_pagamento or ""),
                "link_pagamento": link_pagamento or getattr(venda, "link_pagamento", None),
                "odoo_feedback": {
                    "pedido_criado": bool(pedido_criado),
                    "pedido_confirmado": bool(pedido_confirmado),
                    "parcelas_geradas": bool((resultado_parcelas or {}).get("ok")),
                    "parcelas_message": (resultado_parcelas or {}).get("message"),
                },
            }

            logger.warning("===================================")
            logger.warning("RETORNANDO AJAX abrir_registro_no_painel")
            logger.warning("payload: %s", payload)
            logger.warning("===================================")

            return JsonResponse(payload)

        except Exception as e:
            logger.exception("ERRO AO MONTAR JsonResponse FINAL: %s", e)
            return JsonResponse(
                {
                    "ok": False,
                    "message": f"Erro no retorno final da view: {e}",
                },
                status=500,
            )

    messages.success(request, mensagem_final)
    return redirect("pedido:index")

def _buscar_venda_por_token(token: str) -> Venda | None:
    venda = None

    if hasattr(Venda, "token_pagamento_credito"):
        venda = Venda.objects.filter(token_pagamento_credito=token).first()

    if not venda and hasattr(Venda, "token_pagamento"):
        venda = Venda.objects.filter(token_pagamento=token).first()
    
    return venda

def _valor_venda_em_centavos(venda: Venda) -> int:
    def parse_money(v):
        if v in (None, "", 0, 0.0):
            return None
        try:
            return int(round(float(v) * 100))
        except Exception:
            pass
        try:
            s = str(v).strip()
            s = re.sub(r"[^\d,.\-]", "", s)
            if "," in s and "." in s:
                s = s.replace(".", "").replace(",", ".")
            elif "," in s:
                s = s.replace(",", ".")
            return int(round(float(s) * 100))
        except Exception:
            return None

    candidatos = [
        getattr(venda, "valor_total", None),
        getattr(venda, "valor_final", None),
        getattr(venda, "valor", None),
        getattr(venda, "total", None),
        getattr(venda, "valor_avista", None),
    ]

    for valor in candidatos:
        parsed = parse_money(valor)
        if parsed and parsed > 0:
            return parsed

    registro = getattr(venda, "registro_origem", None)
    if registro:
        for valor in [
            getattr(registro, "valor_total", None),
            getattr(registro, "total", None),
            getattr(registro, "valor_final", None),
            getattr(registro, "valor_avista", None),
            getattr(registro, "avista_total", None),
            getattr(registro, "valor_total_avista", None),
        ]:
            parsed = parse_money(valor)
            if parsed and parsed > 0:
                return parsed

    return 0


def _endpoint_transacoes_rede() -> str:
    sandbox = bool(getattr(settings, "REDE_SANDBOX", True))
    if sandbox:
        return "https://sandbox-erede.useredecloud.com.br/v2/transactions"
    return "https://api.userede.com.br/erede/v2/transactions"

@ensure_csrf_cookie
@require_http_methods(["GET"])
def pagina_pagamento_cartao(request: HttpRequest, token: str) -> HttpResponse:
    venda = _buscar_venda_por_token(token)

    if not venda:
        return HttpResponse("Link de pagamento inválido ou não encontrado.", status=404)

    if venda.status == Venda.StatusChoices.COTACAO:
        venda.status = Venda.StatusChoices.AGUARDANDO_PAGAMENTO
        venda.save(update_fields=["status"])

    contexto = {
        "venda": venda,
        "token": token,
        "link_pagar": reverse("pedido:api_pagamento_cartao_pagar", kwargs={"token": token}),
    }
    return render(request, "pedido/pagamento_cartao.html", contexto)

def _enviar_comprovante_pagamento_rede_para_odoo(venda, raw: dict, valor_base: float) -> dict:
    if not getattr(venda, "odoo_sale_order_id", None):
        return {"ok": False, "message": "Venda sem odoo_sale_order_id."}

    try:
        odoo = _odoo_client()
        sale_order_id = int(venda.odoo_sale_order_id)

        erro_write = None
        try:
            odoo.sale_order_write(sale_order_id, {})
        except Exception as e:
            erro_write = str(e)

        authorization = raw.get("authorization", {}) if isinstance(raw, dict) else {}
        capture = raw.get("capture", {}) if isinstance(raw, dict) else {}

        tid = authorization.get("tid") or raw.get("tid") or ""
        nsu = authorization.get("nsu") or capture.get("nsu") or raw.get("nsu") or ""
        authorization_code = authorization.get("authorizationCode") or raw.get("authorizationCode") or ""
        brand_tid = capture.get("brandTid") or raw.get("brandTid") or ""
        transaction_link_id = raw.get("transactionLinkId") or ""

        date_time = (
            authorization.get("dateTime")
            or capture.get("dateTime")
            or raw.get("dateTime")
            or raw.get("requestDateTime")
            or ""
        )

        amount = authorization.get("amount") or capture.get("amount") or raw.get("amount") or 0
        installments = authorization.get("installments") or raw.get("installments") or 1
        card_bin = authorization.get("cardBin") or raw.get("cardBin") or ""
        last4 = authorization.get("last4") or raw.get("last4") or ""
        return_code = authorization.get("returnCode") or raw.get("returnCode") or ""
        return_message = authorization.get("returnMessage") or raw.get("returnMessage") or ""
        reference = authorization.get("reference") or raw.get("reference") or f"VENDA{getattr(venda, 'id', '')}"

        valor_pago = (float(amount) / 100.0) if amount else float(valor_base or 0)
        cartao_mask = f"{card_bin}******{last4}" if (card_bin or last4) else ""

        comprovante = f"""
Venda local: #{getattr(venda, "id", "")}
Referência: {reference}
Status Rede: {return_message}
Código retorno: {return_code}

TID: {tid}
NSU: {nsu}
Autorização: {authorization_code}

Data/hora: {date_time}
Valor pago: R$ {valor_pago:.2f}
Parcelas: {installments}x
Cartão: {cartao_mask}
""".strip()

        nota_id = None

        # =========================================================
        # GERAÇÃO DO PDF E ENVIO PARA O ODOO
        # =========================================================
        if HTML:
            html_string = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="border: 2px solid #e5e7eb; padding: 25px; border-radius: 12px; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #0a2e5a; margin-top: 0; text-align: center;">💳 Comprovante de Pagamento</h2>
                    <hr style="border: 0; border-top: 1px solid #e5e7eb; margin-bottom: 20px;">
                    <pre style="font-family: monospace; font-size: 14px; white-space: pre-wrap; background: #f8fafc; padding: 15px; border-radius: 8px;">{comprovante}</pre>
                    <p style="text-align: center; font-size: 11px; color: #94a3b8; margin-top: 20px;">
                        Documento gerado automaticamente pelo Painel de Vendas.<br>Cotação mantida sem confirmação automática.
                    </p>
                </div>
            </body>
            </html>
            """
            pdf_bytes = HTML(string=html_string).write_pdf()
            nome_arq = f"Comprovante_Cartao_{tid or reference}.pdf"

            attachment_id = odoo.anexar_arquivo_em_sale_order(
                sale_order_id=sale_order_id,
                nome_arquivo=nome_arq,
                conteudo=pdf_bytes,
                mimetype="application/pdf"
            )
            odoo.postar_anexo_no_chatter(
                sale_order_id,
                attachment_id,
                body="Comprovante de pagamento (Cartão) gerado em PDF inviolável."
            )
            nota_id = attachment_id # Reaproveita a variável para retornar algo
        else:
            # Fallback: Se o WeasyPrint falhar, manda como texto normal
            nota_id = odoo.adicionar_nota_interna_pedido(sale_order_id, comprovante)

        return {
            "ok": True,
            "message": "Comprovante enviado ao Odoo com sucesso.",
            "nota_id": nota_id,
            "erro_write": erro_write,
        }

    except Exception as e:
        logger.warning("ERRO AO ENVIAR COMPROVANTE REDE PARA O ODOO: %s", repr(e))
        return {"ok": False, "message": str(e)}
    
@csrf_exempt
@require_http_methods(["GET", "POST"])
def three_d_secure_success(request: HttpRequest, venda_id: int) -> HttpResponse:
    logger.warning("\n================ 3DS SUCCESS ================")

    try:
        venda = Venda.objects.get(id=venda_id)
    except Venda.DoesNotExist:
        return HttpResponse("Venda não encontrada.", status=404)

    resultado = {
        "ok": False,
        "approved": False,
        "message": "Autenticação 3DS concluída, mas o pagamento ainda está sendo confirmado.",
    }

    if venda.status != Venda.StatusChoices.PAGO:
        resultado = _confirmar_pagamento_3ds(venda)

    venda.refresh_from_db()

    token_venda = getattr(venda, "token_pagamento", "")
    link_pagar = reverse("pedido:api_pagamento_cartao_pagar", kwargs={"token": token_venda}) if token_venda else "#"

    if resultado.get("approved"):
        three_ds_status = "success"
        three_ds_message = "Pagamento confirmado com sucesso."
    else:
        three_ds_status = "pending"
        three_ds_message = resultado.get("message") or "Autenticação 3DS concluída, aguardando confirmação do pagamento."

    return render(
        request,
        "pedido/pagamento_cartao.html",
        {
            "venda": venda,
            "link_pagar": link_pagar,
            "three_ds_status": three_ds_status,
            "three_ds_message": three_ds_message,
            "three_ds_data": resultado.get("raw", {}),
        },
    )

@csrf_exempt
@require_http_methods(["GET", "POST"])
def three_d_secure_failure(request: HttpRequest, venda_id: int) -> HttpResponse:
    logger.warning("\n================ 3DS FAILURE ================")
    logger.warning("VENDA ID: %s", venda_id)
    logger.warning("METHOD: %s", request.method)
    logger.warning("GET: %s", dict(request.GET))
    logger.warning("POST: %s", dict(request.POST))
    logger.warning("=============================================\n")

    try:
        venda = Venda.objects.get(id=venda_id)
    except Venda.DoesNotExist:
        return HttpResponse("Venda não encontrada.", status=404)

    if hasattr(venda, "marcar_pagamento_recusado"):
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])

    return render(
        request,
        "pedido/pagamento_cartao.html",
        {
            "venda": venda,
            "link_pagar": reverse("pedido:api_pagamento_cartao_pagar", kwargs={"token": venda.token_pagamento}),
            "three_ds_status": "failure",
            "three_ds_data": request.POST.dict() if request.method == "POST" else request.GET.dict(),
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def three_d_secure_callback(request: HttpRequest, venda_id: int) -> JsonResponse:
    logger.warning("\n================ 3DS CALLBACK ================")
    logger.warning("VENDA ID: %s", venda_id)
    logger.warning("POST: %s", dict(request.POST))
    logger.warning("BODY: %s", request.body.decode("utf-8", errors="ignore"))
    logger.warning("==============================================\n")

    try:
        venda = Venda.objects.get(id=venda_id)
    except Venda.DoesNotExist:
        return JsonResponse({"ok": False, "message": "Venda não encontrada."}, status=404)

    resultado = _confirmar_pagamento_3ds(venda)
    return JsonResponse(resultado)

@require_http_methods(["POST"])
def api_pagamento_cartao_pagar(request: HttpRequest, token: str) -> JsonResponse:
    logger.warning("\n================ PAGAMENTO CARTAO ================")
    logger.warning("TOKEN RECEBIDO: %s", token)
    logger.warning("CONTENT_TYPE: %s", request.content_type)
    logger.warning("BODY RAW: %s", repr(request.body[:1000]))

    try:
        venda = Venda.objects.get(token_pagamento=token)
        logger.warning("VENDA ID: %s", venda.id)
    except Venda.DoesNotExist:
        logger.warning("ERRO: venda não encontrada")
        return JsonResponse({"ok": False, "message": "Venda não encontrada."}, status=404)

    if (
        venda.status == Venda.StatusChoices.PAGO
        or venda.status_pagamento == Venda.StatusPagamentoChoices.APROVADO
    ):
        return JsonResponse(
            {
                "ok": False,
                "message": f"Esta venda já foi paga anteriormente. Venda #{venda.id}.",
            },
            status=409,
        )

    if venda.status == Venda.StatusChoices.PAGAMENTO_PROCESSANDO:
        return JsonResponse(
            {
                "ok": False,
                "message": "Esta venda já está com pagamento em processamento.",
            },
            status=409,
        )

    try:
        if request.content_type and "application/json" in request.content_type:
            data = json.loads(request.body.decode("utf-8") or "{}")
        else:
            data = request.POST.dict()

        logger.warning("DATA PARSED: %s", data)
    except Exception as e:
        logger.warning("ERRO AO LER BODY: %s", repr(e))
        return JsonResponse(
            {
                "ok": False,
                "message": f"Erro ao ler dados da requisição: {e}",
            },
            status=400,
        )

    def somente_digitos(v):
        return re.sub(r"\D", "", str(v or ""))

    def get_client_ip(req: HttpRequest) -> str:
        x_forwarded_for = req.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return (req.META.get("REMOTE_ADDR") or "").strip()

    nome = (data.get("cardholder_name") or "").strip()
    numero = somente_digitos(data.get("card_number"))
    mes = somente_digitos(data.get("expiration_month")).zfill(2)
    ano = somente_digitos(data.get("expiration_year"))
    cvv = somente_digitos(data.get("security_code"))
    parcelas = int(data.get("installments") or 1)

    if len(ano) == 2:
        ano = f"20{ano}"

    if not nome:
        return JsonResponse({"ok": False, "message": "Nome do titular é obrigatório."}, status=400)

    if len(numero) < 13 or len(numero) > 19:
        return JsonResponse({"ok": False, "message": "Número do cartão inválido."}, status=400)

    if len(mes) != 2 or not (1 <= int(mes) <= 12):
        return JsonResponse({"ok": False, "message": "Mês de expiração inválido."}, status=400)

    if len(ano) != 4:
        return JsonResponse({"ok": False, "message": "Ano de expiração inválido."}, status=400)

    if len(cvv) not in (3, 4):
        return JsonResponse({"ok": False, "message": "CVV inválido."}, status=400)

    valor_base = 0.0
    for equipamento in (venda.equipamentos_json or []):
        valor_base += float(equipamento.get("valor_total", 0) or 0)

    valor_centavos = int(round(valor_base * 100))

    if valor_base <= 0 or valor_centavos <= 0:
        return JsonResponse(
            {
                "ok": False,
                "message": "Não foi possível determinar o valor da venda.",
            },
            status=400,
        )

    pv, token_rede, sandbox = obter_credenciais_rede()
    if sandbox:
        rede_url = "https://sandbox-erede.useredecloud.com.br/v2/transactions"
    else:
        rede_url = "https://api.userede.com.br/erede/v2/transactions"

    if not pv or not token_rede:
        return JsonResponse(
            {
                "ok": False,
                "message": "Credenciais da Rede não configuradas.",
            },
            status=500,
        )

    venda.status = Venda.StatusChoices.PAGAMENTO_PROCESSANDO
    venda.status_pagamento = Venda.StatusPagamentoChoices.PROCESSANDO
    venda.save(update_fields=["status", "status_pagamento"])

    reference = f"VENDA{venda.id}-{uuid.uuid4().hex[:8]}"

    nomes_equipamentos = []
    for eq in (venda.equipamentos_json or []):
        nome_eq = str(eq.get("nome") or "").strip()
        if nome_eq:
            nomes_equipamentos.append(nome_eq)

    equipamento_principal = nomes_equipamentos[0] if nomes_equipamentos else "COMPRA"
    soft_descriptor = f"EAATA {equipamento_principal}"[:22]

    three_ds = data.get("three_ds") or {}

    user_agent = three_ds.get("user_agent") or request.META.get("HTTP_USER_AGENT", "")
    color_depth = int(three_ds.get("color_depth") or 24)
    java_enabled = bool(three_ds.get("java_enabled"))
    language = three_ds.get("language") or "pt-BR"
    screen_height = int(three_ds.get("screen_height") or 0)
    screen_width = int(three_ds.get("screen_width") or 0)
    time_zone_offset = str(three_ds.get("time_zone_offset") or "0")
    device_type_3ds = three_ds.get("device_type_3ds") or "BROWSER"

    if not user_agent:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": "User-Agent do navegador não foi enviado para o 3DS.",
            },
            status=400,
        )

    if screen_height <= 0 or screen_width <= 0:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": "Dados de tela do dispositivo não foram enviados corretamente para o 3DS.",
            },
            status=400,
        )

    cliente = getattr(venda, "cliente", None)
    if not cliente:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": "Esta venda não possui cliente vinculado para enviar os dados de billing do 3DS.",
            },
            status=400,
        )

    endereco = (getattr(cliente, "endereco", "") or "").strip()
    cidade = (getattr(cliente, "cidade", "") or "").strip()
    cep = (getattr(cliente, "cep", "") or "")
    logger.warning("postalcode %s",cep)
    estado = (getattr(cliente, "uf", "") or "").strip()
    email = (getattr(cliente, "email", "") or "").strip()
    telefone = somente_digitos(getattr(cliente, "telefone", "") or "")

    campos_billing_faltando = []

    if not endereco:
        campos_billing_faltando.append("endereco")
    if not cidade:
        campos_billing_faltando.append("cidade")
    if not cep:
        campos_billing_faltando.append("cep")
    if not estado:
        campos_billing_faltando.append("uf")
    if not email:
        campos_billing_faltando.append("email")
    if not telefone:
        campos_billing_faltando.append("telefone")

    if campos_billing_faltando:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": "Dados obrigatórios de billing do 3DS estão incompletos.",
                "missing_fields": campos_billing_faltando,
            },
            status=400,
        )

    ip_address = get_client_ip(request)
    if not ip_address:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": "Não foi possível identificar o IP do cliente para o 3DS.",
            },
            status=400,
        )

    base_url = request.build_absolute_uri('/')[:-1]
    success_url = f"{base_url}/pedido/3ds/s/{venda.id}/"
    failure_url = f"{base_url}/pedido/3ds/f/{venda.id}/"

    payload = {
        "capture": True,
        "kind": "credit",
        "reference": reference,
        "amount": valor_centavos,
        # "softDescriptor": soft_descriptor,
        "installments": parcelas,
        "cardholderName": nome,
        "cardNumber": numero,
        "expirationMonth": int(mes),
        "expirationYear": int(ano),
        "securityCode": cvv,
        
        "threeDSecure": {
            "embedded": True,
            "onFailure": "decline",
            "userAgent": user_agent,
            "ipAddress": ip_address,
            "device": {
                "colorDepth": color_depth,
                "deviceType3ds": "Browser",
                "javaEnabled": java_enabled,
                "language": language,
                "screenHeight": screen_height,
                "screenWidth": screen_width,
                "timeZoneOffset": str(time_zone_offset),
            },
            "billing": {
                "address": endereco,
                "city": cidade,
                "postalCode": cep,
                "state": estado,
                "country": "BRA",
                "emailAddress": email,
                "phoneNumber": telefone,
            }
        },
        "urls": [
            {
                "kind": "threeDSecureSuccess",
                "url": success_url,
            },
            {
                "kind": "threeDSecureFailure",
                "url": failure_url,
            }
        ]
    }

    payload_log = json.loads(json.dumps(payload))
    payload_log["cardNumber"] = numero[:6] + "****" + numero[-4:] if numero else ""
    payload_log["securityCode"] = "***"

    logger.warning("URL TRANSAÇÃO: %s", rede_url)
    logger.warning("PV: %s", pv)
    logger.warning("PAYLOAD: %s", json.dumps(payload_log, ensure_ascii=False, indent=2))

    # =========================================================
    # 1. BUSCA O TOKEN OAUTH 2.0 ANTES DE ENVIAR A REQUISIÇÃO
    # =========================================================
    token_response = obter_access_token_rede()
    if not token_response.get("ok"):
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])
        return JsonResponse(
            {
                "ok": False,
                "message": f"Erro de autenticação na Rede (OAuth): {token_response.get('message')}. Contate o suporte.",
            },
            status=500,
        )
    access_token = token_response.get("access_token")
    # =========================================================

    try:
        resp = requests.post(
            rede_url,
            # 2. SUBSTITUI O BASIC AUTH PELO BEARER TOKEN NO HEADER
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
            timeout=30,
        )

        logger.warning("STATUS REDE: %s", resp.status_code)
        logger.warning("RESPONSE TEXT: %s", resp.text)

        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        logger.warning("RESPONSE JSON: %s", json.dumps(raw, ensure_ascii=False, indent=2))
        logger.warning("=================================================\n")

        if not resp.ok:
            venda.marcar_pagamento_recusado()
            venda.save(update_fields=["status", "status_pagamento"])

            return JsonResponse(
                {
                    "ok": False,
                    "message": raw.get("returnMessage") or raw.get("text") or "Erro na transação.",
                    "returnCode": raw.get("returnCode"),
                    "raw": raw,
                },
                status=400,
            )

        # =========================================================
        # INTERCEPTA O 3DS AQUI!
        # =========================================================
        three_ds_response = raw.get("threeDSecure", {})
        url_banco_3ds = three_ds_response.get("url")

        if url_banco_3ds:
            venda.rede_reference = reference
            venda.rede_tid = raw.get("tid", "")
            venda.save(update_fields=["rede_reference", "rede_tid"])

            return JsonResponse({
                "ok": True,
                "is_3ds": True,
                "url_3ds": url_banco_3ds,
                "message": "Redirecionando para autenticação de segurança do banco..."
            })

        # =========================================================
        # SE CAIR AQUI, NÃO TEVE DESAFIO 3DS (Pagamento aprovado direto)
        # =========================================================
        venda.rede_reference = reference
        venda.rede_tid = raw.get("tid", "")
        venda.rede_nsu = raw.get("nsu", "")
        venda.rede_authorization_code = raw.get("authorizationCode", "")
        venda.marcar_pago()
        venda.save(update_fields=[
            "rede_reference", "rede_tid", "rede_nsu",
            "rede_authorization_code", "status", "status_pagamento",
            "token_pagamento", "link_pagamento",
        ])
        _confirmar_pedido_no_odoo(venda)
        odoo_sync = _enviar_comprovante_pagamento_rede_para_odoo(
            venda=venda,
            raw=raw,
            valor_base=valor_base,
        )

        return JsonResponse(
            {
                "ok": True,
                "is_3ds": False,
                "message": raw.get("returnMessage") or "Pagamento processado com sucesso.",
                "tid": raw.get("tid"),
                "nsu": raw.get("nsu"),
                "authorizationCode": raw.get("authorizationCode"),
                "raw": raw,
                "odoo": odoo_sync,
            }
        )

    except Exception as e:
        venda.marcar_pagamento_recusado()
        venda.save(update_fields=["status", "status_pagamento"])

        logger.warning("ERRO REQUEST REDE: %s", repr(e))
        logger.warning("=================================================\n")
        return JsonResponse(
            {
                "ok": False,
                "message": str(e),
            },
            status=500,
        )
        
def _endpoint_consulta_transacao_rede() -> str:
    sandbox = bool(getattr(settings, "REDE_SANDBOX", True))
    if sandbox:
        return "https://sandbox-erede.useredecloud.com.br/v2/transactions"
    return "https://api.userede.com.br/erede/v2/transactions"

def _status_pix_from_raw(raw: dict) -> str:
    return (
        raw.get("authorization", {}).get("status")
        or raw.get("qrCodeResponse", {}).get("status")
        or raw.get("status")
        or ""
    )


def _pix_qrcode_data_from_raw(raw: dict) -> str:
    return (
        raw.get("qrCodeResponse", {}).get("qrCodeData")
        or raw.get("qrCodeData")
        or raw.get("payload")
        or raw.get("emv")
        or ""
    )


def _pix_qrcode_image_from_raw(raw: dict) -> str:
    return (
        raw.get("qrCodeResponse", {}).get("qrCodeImage")
        or raw.get("qrCodeImage")
        or raw.get("base64Image")
        or raw.get("qrcodeBase64")
        or ""
    )


def _pix_tid_from_raw(raw: dict) -> str:
    return (
        raw.get("authorization", {}).get("tid")
        or raw.get("qrCodeResponse", {}).get("tid")
        or raw.get("tid")
        or raw.get("id")
        or ""
    )


def _pix_expiration_from_raw(raw: dict, fallback: str = "") -> str:
    return (
        raw.get("qrCodeResponse", {}).get("expirationQrCode")
        or raw.get("qrCodeResponse", {}).get("dateTimeExpiration")
        or fallback
    )


def _enviar_comprovante_pagamento_pix_para_odoo(venda, raw: dict, valor_base: float) -> dict:
    if not getattr(venda, "odoo_sale_order_id", None):
        return {"ok": False, "message": "Venda sem odoo_sale_order_id."}

    try:
        odoo = _odoo_client()
        sale_order_id = int(venda.odoo_sale_order_id)

        authorization = raw.get("authorization", {}) or {}
        capture = raw.get("capture", {}) or {}

        tid = authorization.get("tid") or raw.get("tid") or ""
        reference = authorization.get("reference") or raw.get("reference") or f"PIX{getattr(venda, 'id', '')}"
        status_pix = authorization.get("status") or raw.get("status") or ""
        return_code = authorization.get("returnCode") or raw.get("returnCode") or ""
        return_message = authorization.get("returnMessage") or raw.get("returnMessage") or ""
        amount = authorization.get("amount") or raw.get("amount") or 0
        date_time = capture.get("dateTime") or authorization.get("dateTime") or raw.get("dateTime") or ""
        txid = authorization.get("txId") or authorization.get("txid") or ""

        comprovante = f"""
Venda local: #{getattr(venda, "id", "")}
Referência: {reference}
Status Rede: {status_pix}
Retorno: {return_message}

TID: {tid}
TXID: {txid}

Data/hora: {date_time}
Valor pago: R$ {valor_base:.2f}
""".strip()

        nota_id = None

        if HTML:
            html_string = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="border: 2px solid #10b981; padding: 25px; border-radius: 12px; max-width: 600px; margin: 0 auto;">
                    <h2 style="color: #047857; margin-top: 0; text-align: center;">❖ Comprovante de Pagamento PIX</h2>
                    <hr style="border: 0; border-top: 1px solid #a7f3d0; margin-bottom: 20px;">
                    <pre style="font-family: monospace; font-size: 14px; white-space: pre-wrap; background: #ecfdf5; padding: 15px; border-radius: 8px;">{comprovante}</pre>
                    <p style="text-align: center; font-size: 11px; color: #64748b; margin-top: 20px;">
                        Documento gerado automaticamente pelo Painel de Vendas.<br>Cotação mantida sem confirmação automática.
                    </p>
                </div>
            </body>
            </html>
            """
            pdf_bytes = HTML(string=html_string).write_pdf()
            nome_arq = f"Comprovante_PIX_{tid or reference}.pdf"

            attachment_id = odoo.anexar_arquivo_em_sale_order(
                sale_order_id=sale_order_id,
                nome_arquivo=nome_arq,
                conteudo=pdf_bytes,
                mimetype="application/pdf"
            )
            odoo.postar_anexo_no_chatter(
                sale_order_id,
                attachment_id,
                body="Comprovante de pagamento (PIX) gerado em PDF inviolável."
            )
            nota_id = attachment_id
        else:
            nota_id = odoo.adicionar_nota_interna_pedido(sale_order_id, comprovante)

        return {
            "ok": True,
            "message": "Comprovante PIX enviado ao Odoo com sucesso.",
            "nota_id": nota_id,
        }

    except Exception as e:
        logger.warning("ERRO AO ENVIAR COMPROVANTE PIX PARA O ODOO: %s", repr(e))
        return {"ok": False, "message": str(e)}

def _status_pix_aprovado(raw: dict) -> bool:
    authorization = raw.get("authorization", {}) if isinstance(raw, dict) else {}
    status_pix = str(
        authorization.get("status")
        or raw.get("status")
        or raw.get("qrCodeResponse", {}).get("status")
        or ""
    ).strip().lower()

    return_code = str(
        authorization.get("returnCode")
        or raw.get("returnCode")
        or ""
    ).strip()

    return status_pix == "approved" or return_code == "00"


def _confirmar_pagamento_pix(venda, raw: dict | None = None) -> dict:
    """
    Confirma o PIX da venda, atualiza status local e envia comprovante ao Odoo.
    Pode usar `raw` vindo do callback ou consultar a Rede via pix_tid.
    """
    raw = raw or {}
    tid = str(getattr(venda, "pix_tid", "") or "").strip()

    if not raw:
        if not tid:
            return {
                "ok": False,
                "approved": False,
                "message": "Venda sem pix_tid para confirmação automática.",
                "raw": {},
            }

        resultado = consultar_pix_rede(tid)
        raw = resultado.get("raw") or {}
        if not resultado.get("ok"):
            return {
                "ok": False,
                "approved": False,
                "message": resultado.get("message") or "Falha ao consultar PIX na Rede.",
                "raw": raw,
            }

    if not raw:
        return {
            "ok": False,
            "approved": False,
            "message": "A Rede não retornou dados do PIX.",
            "raw": {},
        }

    authorization = raw.get("authorization", {}) if isinstance(raw, dict) else {}
    capture = raw.get("capture", {}) if isinstance(raw, dict) else {}

    aprovado = _status_pix_aprovado(raw)
    status_pix = _status_pix_from_raw(raw)

    campos_update = []

    if hasattr(venda, "pix_tid"):
        novo_tid = authorization.get("tid") or raw.get("tid") or getattr(venda, "pix_tid", "")
        if novo_tid != getattr(venda, "pix_tid", ""):
            venda.pix_tid = novo_tid
            campos_update.append("pix_tid")

    if hasattr(venda, "rede_tid"):
        novo_rede_tid = authorization.get("tid") or raw.get("tid") or getattr(venda, "rede_tid", "")
        if novo_rede_tid != getattr(venda, "rede_tid", ""):
            venda.rede_tid = novo_rede_tid
            campos_update.append("rede_tid")

    if hasattr(venda, "rede_reference"):
        nova_ref = authorization.get("reference") or raw.get("reference") or getattr(venda, "rede_reference", "")
        if nova_ref != getattr(venda, "rede_reference", ""):
            venda.rede_reference = nova_ref
            campos_update.append("rede_reference")

    if hasattr(venda, "rede_nsu"):
        novo_nsu = capture.get("nsu") or authorization.get("nsu") or getattr(venda, "rede_nsu", "")
        if novo_nsu != getattr(venda, "rede_nsu", ""):
            venda.rede_nsu = novo_nsu
            campos_update.append("rede_nsu")

    if hasattr(venda, "rede_authorization_code"):
        novo_auth_code = authorization.get("authorizationCode") or authorization.get("returnCode") or getattr(venda, "rede_authorization_code", "")
        if novo_auth_code != getattr(venda, "rede_authorization_code", ""):
            venda.rede_authorization_code = novo_auth_code
            campos_update.append("rede_authorization_code")

    if aprovado:
        if hasattr(venda, "marcar_pago"):
            venda.marcar_pago()
            _confirmar_pedido_no_odoo(venda)
            campos_update.extend(["status", "status_pagamento"])
        else:
            if hasattr(venda, "status"):
                venda.status = Venda.StatusChoices.PAGO
                campos_update.append("status")
            if hasattr(venda, "status_pagamento"):
                venda.status_pagamento = Venda.StatusPagamentoChoices.APROVADO
                campos_update.append("status_pagamento")
    else:
        if hasattr(venda, "status") and venda.status != Venda.StatusChoices.AGUARDANDO_PAGAMENTO:
            venda.status = Venda.StatusChoices.AGUARDANDO_PAGAMENTO
            campos_update.append("status")
        if hasattr(venda, "status_pagamento") and venda.status_pagamento != Venda.StatusPagamentoChoices.PENDENTE:
            venda.status_pagamento = Venda.StatusPagamentoChoices.PENDENTE
            campos_update.append("status_pagamento")

    if campos_update:
        venda.save(update_fields=list(dict.fromkeys(campos_update)))

    odoo_sync = None
    if aprovado:
        valor_base = _valor_venda_em_centavos(venda) / 100.0
        odoo_sync = _enviar_comprovante_pagamento_pix_para_odoo(
            venda=venda,
            raw=raw,
            valor_base=valor_base,
        )

    return {
        "ok": True,
        "approved": aprovado,
        "message": "PIX aprovado." if aprovado else f"Status atual do PIX: {status_pix or 'pendente'}",
        "status_pix": status_pix,
        "raw": raw,
        "odoo": odoo_sync,
    }

@ensure_csrf_cookie
@require_http_methods(["GET"])
def pagina_pagamento_pix(request: HttpRequest, token: str) -> HttpResponse:
    venda = _buscar_venda_por_token(token)

    if not venda:
        return HttpResponse("Link de pagamento PIX inválido ou não encontrado.", status=404)

    contexto = {
        "venda": venda,
        "token": token,
        "link_gerar": reverse("pedido:api_pagamento_pix_gerar_qrcode", kwargs={"token": token}),
        "link_consultar": reverse("pedido:api_pagamento_pix_consultar", kwargs={"token": token}),
        "pix_existente_data": getattr(venda, "codigo_pix", "") or "",
        "pix_existente_imagem": getattr(venda, "codigo_pix_imagem", "") or "",
    }
    return render(request, "pedido/pagamento_pix.html", contexto)


@require_http_methods(["POST"])
def api_pagamento_pix_gerar_qrcode(request: HttpRequest, token: str) -> JsonResponse:
    venda = _buscar_venda_por_token(token)
    if not venda:
        return JsonResponse({"ok": False, "message": "Venda não encontrada."}, status=404)

    valor_centavos = _valor_venda_em_centavos(venda)
    if valor_centavos <= 0:
        return JsonResponse({"ok": False, "message": "Valor da venda inválido para gerar PIX."}, status=400)

    qr_data_existente = getattr(venda, "codigo_pix", "") or ""
    qr_image_existente = getattr(venda, "codigo_pix_imagem", "") or ""
    tid_existente = getattr(venda, "pix_tid", "") or ""
    reference_existente = getattr(venda, "rede_reference", "") or ""
    expira_em_existente = getattr(venda, "pix_expira_em", None)

    pix_ainda_valido = False
    if expira_em_existente:
        try:
            exp_ref = expira_em_existente
            if timezone.is_naive(exp_ref):
                exp_ref = timezone.make_aware(exp_ref, timezone.get_current_timezone())
            pix_ainda_valido = exp_ref > timezone.now()
        except Exception:
            pix_ainda_valido = False

    if qr_data_existente and pix_ainda_valido:
        logger.warning("===================================")
        logger.warning("PIX JÁ EXISTENTE - REAPRESENTANDO")
        logger.warning("venda.id: %s", venda.id)
        logger.warning("pix_tid: %s", tid_existente)
        logger.warning("rede_reference: %s", reference_existente)
        logger.warning("pix_expira_em: %s", expira_em_existente)
        logger.warning("===================================")

        return JsonResponse(
            {
                "ok": True,
                "message": "QR Code PIX já havia sido gerado. Reapresentando o código salvo.",
                "reference": reference_existente or f"PIX{venda.id}",
                "amount": valor_centavos,
                "expires_at": expira_em_existente.isoformat() if expira_em_existente else None,
                "status_pix": "pending",
                "tid": tid_existente,
                "qr_code_data": qr_data_existente,
                "qr_code_image": qr_image_existente,
                "raw": {
                    "reused": True,
                    "source": "venda",
                },
            },
            status=200,
        )

    expires_at = (timezone.now() + timedelta(minutes=30)).astimezone().replace(microsecond=0).isoformat()
    reference = f"PIX{venda.id}{uuid.uuid4().hex[:8]}".upper()[:16]
    logger.warning("Gerando novo PIX na Rede para venda.id %s com reference %s", venda.id, reference)

    callback_path = reverse("pedido:api_pagamento_pix_notificacao")
    public_base_url = str(getattr(settings, "PUBLIC_BASE_URL", "") or "").strip()

    if public_base_url:
        callback_url = urljoin(public_base_url.rstrip("/") + "/", callback_path.lstrip("/"))
    else:
        callback_url = request.build_absolute_uri(callback_path)

    logger.warning("Callback URL PIX fixa: %s", callback_url)

    _pv_rede, _token_rede, sandbox_rede = obter_credenciais_rede()
    registrar_em_sandbox = _env_bool(getattr(settings, "REDE_WEBHOOK_REGISTER_IN_SANDBOX", False), False)

    if sandbox_rede and registrar_em_sandbox:
        logger.warning("Registrando webhook PIX na sandbox da Rede: %s", callback_url)
        registro_callback = registrar_notification_url_rede_sandbox(callback_url)

        if not registro_callback.get("ok"):
            logger.warning("Falha ao registrar webhook PIX no sandbox; geração do QR continuará. retorno=%s", registro_callback)

    resultado = gerar_payload_pix_rede(
        amount=valor_centavos,
        reference=reference,
        expires_at=expires_at,
        notification_url=callback_url,
    )

    raw = resultado.get("raw") or {}
    mensagem = str(resultado.get("message") or "")

    if (
        not resultado.get("ok")
        and "already exists" in mensagem.lower()
        and getattr(venda, "codigo_pix", "")
    ):
        logger.warning("===================================")
        logger.warning("REFERENCE DUPLICADA NA REDE - REAPROVEITANDO PIX LOCAL")
        logger.warning("venda.id: %s", venda.id)
        logger.warning("===================================")

        return JsonResponse(
            {
                "ok": True,
                "message": "Este PIX já havia sido gerado. Reapresentando o QR salvo.",
                "reference": getattr(venda, "rede_reference", "") or reference,
                "amount": valor_centavos,
                "expires_at": getattr(venda, "pix_expira_em", None).isoformat() if getattr(venda, "pix_expira_em", None) else expires_at,
                "status_pix": "pending",
                "tid": getattr(venda, "pix_tid", ""),
                "qr_code_data": getattr(venda, "codigo_pix", ""),
                "qr_code_image": getattr(venda, "codigo_pix_imagem", ""),
                "raw": {
                    "reused": True,
                    "source": "fallback_after_reference_exists",
                    "gateway_raw": raw,
                },
            },
            status=200,
        )

    qr_data = _pix_qrcode_data_from_raw(raw)
    qr_image = _pix_qrcode_image_from_raw(raw)
    tid = _pix_tid_from_raw(raw)
    status_pix = _status_pix_from_raw(raw)
    expira_em = _pix_expiration_from_raw(raw, fallback=expires_at)

    campos_update = []

    if hasattr(venda, "status"):
        venda.status = Venda.StatusChoices.AGUARDANDO_PAGAMENTO
        campos_update.append("status")

    if hasattr(venda, "status_pagamento"):
        venda.status_pagamento = Venda.StatusPagamentoChoices.PENDENTE
        campos_update.append("status_pagamento")

    if hasattr(venda, "token_pagamento") and not getattr(venda, "token_pagamento", None):
        venda.token_pagamento = token
        campos_update.append("token_pagamento")

    if qr_data:
        venda.codigo_pix = qr_data
        campos_update.append("codigo_pix")

    if qr_image:
        venda.codigo_pix_imagem = qr_image
        campos_update.append("codigo_pix_imagem")

    if tid:
        venda.pix_tid = tid
        campos_update.append("pix_tid")

    venda.rede_reference = resultado.get("reference") or reference
    campos_update.append("rede_reference")

    if expira_em:
        try:
            venda.pix_expira_em = timezone.datetime.fromisoformat(str(expira_em).replace("Z", "+00:00"))
            campos_update.append("pix_expira_em")
        except Exception:
            pass

    if campos_update:
        venda.save(update_fields=list(dict.fromkeys(campos_update)))

    return JsonResponse(
        {
            "ok": bool(resultado.get("ok")),
            "message": resultado.get("message"),
            "reference": resultado.get("reference") or reference,
            "amount": valor_centavos,
            "expires_at": expira_em,
            "status_pix": status_pix,
            "tid": tid,
            "qr_code_data": qr_data,
            "qr_code_image": qr_image,
            "raw": raw,
        },
        status=200 if resultado.get("ok") else 400,
    )

@require_http_methods(["GET"])
def api_pagamento_pix_consultar(request: HttpRequest, token: str) -> JsonResponse:
    venda = _buscar_venda_por_token(token)
    if not venda:
        return JsonResponse({"ok": False, "message": "Venda não encontrada."}, status=404)

    resultado = _confirmar_pagamento_pix(venda)

    return JsonResponse(
        {
            "ok": bool(resultado.get("ok")),
            "message": resultado.get("message"),
            "status_pix": resultado.get("status_pix"),
            "pago": bool(resultado.get("approved")),
            "tid": getattr(venda, "pix_tid", ""),
            "raw": resultado.get("raw") or {},
            "odoo": resultado.get("odoo"),
        },
        status=200 if resultado.get("ok") else 400,
    )

@csrf_exempt
@require_http_methods(["POST"])
def api_pagamento_pix_notificacao(request: HttpRequest) -> JsonResponse:
    if not _validar_auth_webhook_rede(request):
        return JsonResponse(
            {"ok": False, "message": "Unauthorized webhook."},
            status=401,
        )

    body_text = request.body.decode("utf-8", errors="ignore")

    logger.warning("========== PIX CALLBACK ==========")
    logger.warning("method=%s", request.method)
    logger.warning("BODY=%s", body_text[:5000])

    raw_callback = {}
    if body_text:
        try:
            raw_callback = json.loads(body_text)
        except Exception:
            return JsonResponse(
                {"ok": False, "message": "Payload inválido."},
                status=400,
            )

    evento_tid = str(
        (raw_callback.get("data") or {}).get("id")
        or raw_callback.get("id")
        or ""
    ).strip()

    evento_reference = str(
        (raw_callback.get("data") or {}).get("reference")
        or raw_callback.get("reference")
        or ""
    ).strip()

    if not evento_tid and not evento_reference:
        return JsonResponse(
            {"ok": False, "message": "Webhook sem TID/reference."},
            status=400,
        )

    venda = _buscar_venda_por_pix_tid_ou_reference(
        tid=evento_tid,
        reference=evento_reference,
    )
    if not venda:
        return JsonResponse(
            {
                "ok": False,
                "message": "Venda não encontrada para o webhook.",
                "tid": evento_tid,
                "reference": evento_reference,
            },
            status=404,
        )

    if evento_tid and hasattr(venda, "pix_tid") and evento_tid != (getattr(venda, "pix_tid", "") or ""):
        venda.pix_tid = evento_tid
        venda.save(update_fields=["pix_tid"])

    consulta_tid = evento_tid or str(getattr(venda, "pix_tid", "") or "").strip()
    if not consulta_tid:
        return JsonResponse(
            {"ok": False, "message": "Venda encontrada sem pix_tid para consulta."},
            status=400,
        )

    consulta = consultar_pix_rede(consulta_tid)
    raw_transacao = consulta.get("raw") or {}

    resultado = _confirmar_pagamento_pix(venda, raw=raw_transacao)

    return JsonResponse(
        {
            "ok": bool(resultado.get("ok")),
            "approved": bool(resultado.get("approved")),
            "message": resultado.get("message"),
            "status_pix": resultado.get("status_pix"),
            "tid": consulta_tid,
            "venda_id": venda.id,
        },
        status=200,
    )