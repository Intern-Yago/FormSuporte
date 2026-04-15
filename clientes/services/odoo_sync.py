# clientes/services/odoo_sync.py
from __future__ import annotations

import requests
import logging
from django.conf import settings
from clientes.integrations.odoo_client import OdooClient, OdooConfig

logger = logging.getLogger(__name__)

class RateLimitError(Exception):
    """Exceção para quando as APIs atingem o limite de requisições."""
    pass

def _only_digits(v: str) -> str:
    return "".join(ch for ch in (v or "") if ch.isdigit())


def _odoo() -> OdooClient:
    cfg = OdooConfig(
        url=settings.ODOO_URL,
        db=settings.ODOO_DB,
        username=settings.ODOO_USER,
        password=settings.ODOO_PASSWORD,
    )
    return OdooClient(cfg)


def lookup_cnpj_info(cnpj: str) -> dict | None:
    """
    Consulta dados do CNPJ. Tenta CNPJA e BrasilAPI como fallback.
    """
    cnpj_limpo = _only_digits(cnpj)
    if not cnpj_limpo or len(cnpj_limpo) != 14:
        return None
    
    rate_limited = False

    # 1. Tenta CNPJA
    url_cnpja = f"https://open.cnpja.com/office/{cnpj_limpo}"
    try:
        res = requests.get(url_cnpja, timeout=8)
        if res.status_code == 200:
            data = res.json()
            return {
                "razao": data.get("company", {}).get("name"),
                "email": (data.get("emails") or [{}])[0].get("address"),
                "telefone": f"{(data.get('phones') or [{}])[0].get('area', '')}{(data.get('phones') or [{}])[0].get('number', '')}",
                "rua": data.get("address", {}).get("street"),
                "numero": data.get("address", {}).get("number"),
                "complemento": data.get("address", {}).get("details"),
                "bairro": data.get("address", {}).get("district"),
                "cidade": data.get("city", {}).get("name"),
                "uf": data.get("state", {}).get("code"),
                "cep": data.get("address", {}).get("zip"),
            }
        elif res.status_code == 429:
            rate_limited = True
            logger.warning(f"CNPJA limit hit (429) for {cnpj_limpo}.")
    except Exception as e:
        logger.error(f"Erro CNPJA: {e}")

    # 2. Fallback BrasilAPI
    url_brasil = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    try:
        res = requests.get(url_brasil, timeout=8)
        if res.status_code == 200:
            data = res.json()
            return {
                "razao": data.get("razao_social"),
                "email": data.get("email"),
                "telefone": f"{data.get('ddd_telefone_1', '')}{data.get('telefone_1', '')}",
                "rua": data.get("logradouro"),
                "numero": data.get("numero"),
                "complemento": data.get("complemento"),
                "bairro": data.get("bairro"),
                "cidade": data.get("municipio"),
                "uf": data.get("uf"),
                "cep": data.get("cep"),
            }
        elif res.status_code == 429:
            rate_limited = True
    except Exception as e:
        logger.error(f"Erro BrasilAPI: {e}")
    
    if rate_limited:
        raise RateLimitError("Limite de consultas atingido. Tente novamente em alguns instantes.")
        
    return None


def enrich_cliente_from_cnpj(cliente) -> bool:
    """
    Busca dados em APIs externas e atualiza o cliente local.
    """
    cnpj = _only_digits(getattr(cliente, "cnpj", "") or "")
    if not cnpj or len(cnpj) != 14:
        return False

    data = lookup_cnpj_info(cnpj)
    if not data:
        return False

    local_changed = False
    
    # 1. Razão Social
    api_razao = (data.get("razao") or "").strip()
    if api_razao and cliente.razao_social != api_razao:
        cliente.razao_social = api_razao
        local_changed = True
    
    # 2. Contato
    if data.get("email") and not cliente.email:
        cliente.email = data["email"]
        local_changed = True
    
    if data.get("telefone") and not cliente.telefone:
        tel = _only_digits(data["telefone"])
        if len(tel) >= 8:
            cliente.telefone = tel
            local_changed = True
    
    # 3. Endereço
    if data.get("rua") and not cliente.endereco:
        cliente.endereco = data["rua"]
        cliente.numero = data.get("numero") or ""
        cliente.complemento = data.get("complemento") or ""
        cliente.bairro = data.get("bairro") or ""
        cliente.cidade = data.get("cidade") or ""
        cliente.uf = (data.get("uf") or "").upper()
        cliente.cep = _only_digits(data.get("cep") or "")
        local_changed = True
    
    if local_changed:
        cliente.save()
        return True
    
    return False


def _update_local_from_odoo(cliente, odoo: OdooClient, partner_id: int):
    """
    Busca dados atuais no Odoo e atualiza o Cliente local.
    """
    try:
        fields = [
            "name", "l10n_br_razao_social", "l10n_br_ie", "email", "phone", "mobile", 
            "street", "l10n_br_endereco_numero", "street2", 
            "l10n_br_endereco_bairro", "city", "state_id", "zip",
            "l10n_br_cnpj", "l10n_br_cpf"
        ]
        data = odoo.partner_read(partner_id, fields)
        if not data:
            return

        changed = False
        
        # 0) CPF / CNPJ (se local estiver vazio)
        odoo_cnpj = _only_digits(data.get("l10n_br_cnpj") or "")
        if odoo_cnpj and not cliente.cnpj:
            cliente.cnpj = odoo_cnpj
            changed = True
        
        odoo_cpf = _only_digits(data.get("l10n_br_cpf") or "")
        if odoo_cpf and not cliente.cpf and not cliente.cnpj:
            cliente.cpf = odoo_cpf
            changed = True

        # 1) Nome Fantasia
        odoo_name = (data.get("name") or "").strip()
        if odoo_name and cliente.nome != odoo_name:
            if not cliente.nome or cliente.nome in ["Cliente", "Sem Nome", "Não identificado"]:
                cliente.nome = odoo_name
                changed = True
        
        # 2) Razão Social
        odoo_legal = (data.get("l10n_br_razao_social") or "").strip()
        if odoo_legal and cliente.razao_social != odoo_legal:
            cliente.razao_social = odoo_legal
            changed = True

        # 3) Inscrição Estadual
        odoo_ie = (data.get("l10n_br_ie") or "").strip()
        if odoo_ie and cliente.inscricao_estadual != odoo_ie:
            cliente.inscricao_estadual = odoo_ie
            changed = True

        # 4) Email
        odoo_email = (data.get("email") or "").strip()
        if odoo_email and not cliente.email:
            cliente.email = odoo_email
            changed = True

        # 5) Telefone
        odoo_phone = (data.get("mobile") or data.get("phone") or "").strip()
        if odoo_phone and not cliente.telefone:
            cliente.telefone = odoo_phone
            changed = True

        # 6) Endereço
        if not cliente.endereco and data.get("street"):
            cliente.endereco = data.get("street")
            cliente.numero = data.get("l10n_br_endereco_numero") or ""
            cliente.complemento = data.get("street2") or ""
            cliente.bairro = data.get("l10n_br_endereco_bairro") or ""
            cliente.cidade = data.get("city") or ""
            
            state_info = data.get("state_id")
            if state_info and isinstance(state_info, (list, tuple)) and len(state_info) > 1:
                state_str = state_info[1]
                if "(" in state_str and ")" in state_str:
                    cliente.uf = state_str.split("(")[-1].split(")")[0].strip().upper()
                else:
                    cliente.uf = state_str[:2].strip().upper()
            
            cliente.cep = data.get("zip") or ""
            changed = True

        if changed:
            cliente.save()
    except Exception as e:
        logger.warning(f"Erro ao atualizar dados locais do Odoo para cliente {cliente.id}: {e}")


def ensure_odoo_partner_for_cliente(
    cliente,
    *,
    zip_code: str | None = None,
    street: str | None = None,
    bairro: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    name: str | None = None,
    ie: str | None = None,
    always_update_local: bool = False,
) -> int:
    cnpj = _only_digits(getattr(cliente, "cnpj", "") or "")
    cpf = _only_digits(getattr(cliente, "cpf", "") or "")

    if cnpj and len(cnpj) == 14:
        try:
            enrich_cliente_from_cnpj(cliente)
        except:
            pass

    _email = (email or getattr(cliente, "email", "") or "").strip() or None
    _phone = (phone or getattr(cliente, "telefone", "") or "").strip() or None
    _razao = getattr(cliente, "razao_social", "").strip()
    _name = (name or getattr(cliente, "nome", "") or "Cliente").strip()

    tipo_faturamento = None
    doc = None
    company_type = "person"
    indicador_ie = "9"

    if cnpj:
        tipo_faturamento = "l10n_br_cnpj"
        doc = cnpj
        company_type = "company"
        indicador_ie = False
    elif cpf:
        tipo_faturamento = "l10n_br_cpf"
        doc = cpf
        company_type = "person"
        indicador_ie = "9"

    odoo = _odoo()
    
    cached_id = getattr(cliente, "odoo_partner_id", None)
    partner_id = None

    if cached_id:
        partner_id = int(cached_id)
    else:
        if not any([doc, _email, _phone]):
            raise ValueError("Cliente sem identificadores para sincronizar com Odoo.")
        
        partner_id = odoo.find_partner_by_doc(
            tipo_faturamento=tipo_faturamento,
            doc=doc,
            email=_email,
            phone=_phone,
            name=_name,
        )

    # Prepara valores base de endereço
    _street = (street or getattr(cliente, "endereco", "") or "").strip() or None
    _bairro = (bairro or getattr(cliente, "bairro", "") or "").strip() or None
    z = _only_digits(zip_code or getattr(cliente, "cep", "") or "")
    _zip = z if len(z) == 8 else False
    _ie = (ie or getattr(cliente, "inscricao_estadual", "") or "").strip() or None
    _city = getattr(cliente, "cidade", "")
    _uf = getattr(cliente, "uf", "")

    if partner_id:
        odoo_data = odoo.partner_read(partner_id, ["email", "phone", "mobile", "street", "l10n_br_razao_social"])
        update_vals = {}
        
        if _razao and _razao != (odoo_data.get("l10n_br_razao_social") or "").strip():
            update_vals["l10n_br_razao_social"] = _razao

        if _email and not odoo_data.get("email"): update_vals["email"] = _email
        if _phone and not odoo_data.get("phone") and not odoo_data.get("mobile"):
            update_vals["phone"] = _phone
            update_vals["mobile"] = _phone

        if _street and not odoo_data.get("street"):
            update_vals["street"] = _street
            update_vals["zip"] = _zip
            update_vals["l10n_br_endereco_bairro"] = _bairro
            update_vals["city"] = _city
            try:
                country_id, state_id, city_id = odoo.buscar_ids_endereco(_uf, _city)
                if state_id: update_vals["state_id"] = state_id
                if city_id: update_vals["l10n_br_municipio_id"] = city_id
            except: pass

        # 🔥 Chamada do onchange_l10n_br_consultar_cnpj
        if cnpj and len(cnpj) == 14:
            try:
                update_vals["l10n_br_consultar_cnpj"] = True
                odoo.partner_update(partner_id, update_vals)
                res_onchange = odoo._object.execute_kw(
                    odoo.cfg.db, odoo.uid, odoo.cfg.password,
                    "res.partner", "onchange_l10n_br_consultar_cnpj",
                    [[partner_id]]
                )
                if res_onchange and isinstance(res_onchange, dict) and "value" in res_onchange:
                    odoo.partner_update(partner_id, res_onchange["value"])
            except: pass
        elif update_vals:
            odoo.partner_update(partner_id, update_vals)

        cliente.odoo_partner_id = partner_id
        _update_local_from_odoo(cliente, odoo, partner_id)
        cliente.save()
    else:
        # ✅ Não existe: Cria novo
        vals = {
            "name": _name,
            "email": _email or False,
            "phone": _phone or False,
            "mobile": _phone or False,
            "company_type": company_type,
            "zip": _zip,
            "street": _street or False,
            "l10n_br_endereco_bairro": _bairro or False,
            "l10n_br_indicador_ie": indicador_ie,
            "l10n_br_razao_social": _razao or False,
        }
        if cnpj and len(cnpj) == 14:
            vals["l10n_br_consultar_cnpj"] = True

        try:
            country_id, state_id, city_id = odoo.buscar_ids_endereco(_uf, _city)
            if state_id: vals["state_id"] = state_id
            if city_id: vals["l10n_br_municipio_id"] = city_id
        except: pass

        if tipo_faturamento and doc:
            vals[tipo_faturamento] = doc
        if _ie:
            vals["l10n_br_ie"] = _ie

        partner_id = odoo.partner_create(vals)
        
        if cnpj and len(cnpj) == 14:
            try:
                res_onchange = odoo._object.execute_kw(
                    odoo.cfg.db, odoo.uid, odoo.cfg.password,
                    "res.partner", "onchange_l10n_br_consultar_cnpj",
                    [[partner_id]]
                )
                if res_onchange and isinstance(res_onchange, dict) and "value" in res_onchange:
                    odoo.partner_update(partner_id, res_onchange["value"])
            except: pass

        cliente.odoo_partner_id = int(partner_id)
        _update_local_from_odoo(cliente, odoo, partner_id)
        cliente.save()

    return int(partner_id)


def sync_all_local_to_odoo() -> int:
    """
    Percorre todos os clientes do banco local e tenta vincular/criar no Odoo.
    """
    from clientes.models import Cliente
    clientes = Cliente.objects.all()
    count = 0
    for cliente in clientes:
        try:
            ensure_odoo_partner_for_cliente(cliente)
            count += 1
        except Exception as e:
            logger.error(f"Erro ao sincronizar cliente {cliente.id} com Odoo: {e}")
    return count
