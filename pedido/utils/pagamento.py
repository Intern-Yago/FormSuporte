from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime
from uuid import uuid4

import requests
from django.conf import settings
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)


def gerar_token_interno_pagamento() -> str:
    return uuid4().hex


def _env_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _setting_str(*names: str, default: str = "") -> str:
    for name in names:
        if hasattr(settings, name):
            value = getattr(settings, name)
            if value is None:
                continue
            s = str(value).strip().strip('"').strip("'")
            if s:
                return s
    return default


def obter_credenciais_rede() -> tuple[str, str, bool]:
    sandbox = _env_bool(getattr(settings, "REDE_SANDBOX", True), True)

    if sandbox:
        pv = _setting_str("REDE_CLIENT_ID_s", "REDE_CLIENT_ID")
        token = _setting_str("REDE_CLIENT_SECRET_s", "REDE_CLIENT_SECRET")
    else:
        pv = _setting_str("REDE_CLIENT_ID")
        token = _setting_str("REDE_CLIENT_SECRET")

    logger.info(pv, token, sandbox)

    return pv, token, sandbox


def _mask(value, keep_start=6, keep_end=4):
    s = str(value or "")
    if not s:
        return ""
    if len(s) <= keep_start + keep_end:
        return "*" * len(s)
    return f"{s[:keep_start]}{'*' * (len(s) - keep_start - keep_end)}{s[-keep_end:]}"


def _somente_digitos(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def obter_access_token_rede() -> dict:
    """
    Mantido por compatibilidade com o restante do projeto.
    O fluxo principal do PIX usa Basic Auth no /v2/transactions.
    """
    client_id, client_secret, sandbox = obter_credenciais_rede()

    print("\n========== DEBUG TOKEN REDE ==========")
    print("REDE_SANDBOX:", sandbox)
    print("REDE_CLIENT_ID(raw repr):", repr(client_id))
    print("REDE_CLIENT_ID(mask):", _mask(client_id, 2, 2))
    print("REDE_CLIENT_SECRET(mask):", _mask(client_secret, 4, 4))

    if not client_id or not client_secret:
        print("ERRO: credenciais ausentes.")
        print("======================================\n")
        return {
            "ok": False,
            "message": "REDE_CLIENT_ID / REDE_CLIENT_SECRET não configurados.",
            "access_token": None,
            "expires_in": None,
            "raw": None,
        }

    token_url = (
        "https://rl7-sandbox-api.useredecloud.com.br/oauth2/token"
        if sandbox
        else "https://api.userede.com.br/redelabs/oauth2/token"
    )

    print("TOKEN URL:", token_url)

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")

    try:
        resp = requests.post(
            token_url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=30,
        )

        print("TOKEN STATUS CODE:", resp.status_code)
        print("TOKEN RESPONSE TEXT:", resp.text)

        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        print("TOKEN RESPONSE JSON:", json.dumps(raw, ensure_ascii=False, indent=2))
        print("======================================\n")

        if not resp.ok:
            return {
                "ok": False,
                "message": f"Erro ao autenticar na Rede: HTTP {resp.status_code}",
                "access_token": None,
                "expires_in": None,
                "raw": raw,
            }

        return {
            "ok": True,
            "message": "Token gerado com sucesso.",
            "access_token": raw.get("access_token"),
            "expires_in": raw.get("expires_in"),
            "raw": raw,
        }

    except Exception as e:
        print("EXCEPTION TOKEN REDE:", repr(e))
        print("======================================\n")
        return {
            "ok": False,
            "message": f"Falha ao gerar token da Rede: {e}",
            "access_token": None,
            "expires_in": None,
            "raw": None,
        }


def _endpoint_transacoes_rede() -> str:
    _pv, _token, sandbox = obter_credenciais_rede()
    if sandbox:
        return "https://sandbox-erede.useredecloud.com.br/v2/transactions"
    return "https://api.userede.com.br/erede/v2/transactions"


def _rede_basic_auth() -> HTTPBasicAuth:
    pv, token_rede, _sandbox = obter_credenciais_rede()

    if not pv or not token_rede:
        raise ValueError("REDE_CLIENT_ID / REDE_CLIENT_SECRET não configurados.")

    return HTTPBasicAuth(pv, token_rede)


def _normalizar_reference_pix(reference: str) -> str:
    ref = re.sub(r"[^A-Za-z0-9]", "", str(reference or ""))
    if not ref:
        ref = f"PIX{uuid4().hex[:10]}"
    return ref[:16]


def _normalizar_expiracao_pix(expires_at: str) -> str:
    try:
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return dt.replace(microsecond=0).isoformat()
    except Exception:
        return str(expires_at)


def gerar_payload_pix_rede(*, amount: int, reference: str, expires_at: str, notification_url: str | None = None) -> dict:
    url = _endpoint_transacoes_rede()
    reference_norm = _normalizar_reference_pix(reference)
    expiration_norm = _normalizar_expiracao_pix(expires_at)

    body = {
        "kind": "pix",
        "reference": reference_norm,
        "amount": int(amount),
        "qrCode": {
            "dateTimeExpiration": expiration_norm,
        },
    }

    if notification_url:
        body["urls"] = [{"kind": "callback", "url": str(notification_url).strip()}]

    # 1. Buscar o Token OAuth 2.0 usando a função já existente
    token_response = obter_access_token_rede()
    
    if not token_response.get("ok"):
        return {
            "ok": False,
            "status_code": None,
            "reference": reference_norm,
            "raw": token_response.get("raw"),
            "message": f"Erro de autenticação OAuth: {token_response.get('message')}",
        }
    
    access_token = token_response.get("access_token")

    print("\n========== DEBUG PIX REDE ==========")
    print("URL:", url)
    print("REFERENCE:", reference_norm)
    print("AMOUNT:", amount)
    print("EXPIRATION:", expiration_norm)
    print("NOTIFICATION URL:", notification_url)
    print("BODY:", json.dumps(body, ensure_ascii=False, indent=2))

    # 2. Enviar a requisição usando o Bearer Token no cabeçalho
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json", 
                "Accept": "application/json"
            },
            json=body,
            timeout=30,
        )

        print("PIX STATUS CODE:", resp.status_code)
        print("PIX RESPONSE TEXT:", resp.text)

        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        print("PIX RESPONSE JSON:", json.dumps(raw, ensure_ascii=False, indent=2))
        print("====================================\n")

        return {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "reference": reference_norm,
            "raw": raw,
            "message": (
                raw.get("returnMessage")
                or raw.get("message")
                or raw.get("qrCodeResponse", {}).get("returnMessage")
                or raw.get("authorization", {}).get("returnMessage")
                or f"HTTP {resp.status_code}"
            ),
        }

    except Exception as e:
        print("EXCEPTION PIX REDE:", repr(e))
        print("====================================\n")
        return {
            "ok": False,
            "status_code": None,
            "reference": reference_norm,
            "raw": None,
            "message": f"Erro ao gerar QR Code PIX: {e}",
        }


def consultar_pix_rede(tid: str) -> dict:
    tid = str(tid or "").strip()
    if not tid:
        return {"ok": False, "status_code": None, "raw": None, "message": "TID PIX não informado."}

    url = f"{_endpoint_transacoes_rede()}/{tid}"

    print("\n========== DEBUG CONSULTA PIX ==========")
    print("URL:", url)

    # 1. Buscar o token
    token_response = obter_access_token_rede()
    if not token_response.get("ok"):
        return {
            "ok": False,
            "status_code": None,
            "raw": token_response.get("raw"),
            "message": f"Erro de autenticação OAuth: {token_response.get('message')}",
        }
    access_token = token_response.get("access_token")

    try:
        # 2. Usar o Bearer Token no header
        resp = requests.get(
            url, 
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }, 
            timeout=30
        )

        print("CONSULTA PIX STATUS CODE:", resp.status_code)
        print("CONSULTA PIX RESPONSE TEXT:", resp.text)

        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        print("CONSULTA PIX RESPONSE JSON:", json.dumps(raw, ensure_ascii=False, indent=2))
        print("========================================\n")

        return {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "raw": raw,
            "message": (
                raw.get("message")
                or raw.get("returnMessage")
                or raw.get("qrCodeResponse", {}).get("returnMessage")
                or raw.get("authorization", {}).get("returnMessage")
                or "Consulta realizada."
            ),
        }

    except Exception as e:
        print("EXCEPTION CONSULTA PIX:", repr(e))
        print("========================================\n")
        return {
            "ok": False,
            "status_code": None,
            "raw": None,
            "message": f"Erro ao consultar PIX na Rede: {e}",
        }


def registrar_notification_url_rede_sandbox(callback_url: str) -> dict:
    callback_url = str(callback_url or "").strip()
    logger.warning("Registrando callback URL no sandbox da Rede: %s", callback_url)
    if not callback_url:
        return {"ok": False, "status_code": None, "raw": None, "message": "Callback URL não informada."}

    pv, token_rede, sandbox = obter_credenciais_rede()
    if not sandbox:
        return {"ok": True, "status_code": None, "raw": None, "message": "Registro sandbox ignorado em produção."}

    # 1. Buscar o token
    token_response = obter_access_token_rede()
    if not token_response.get("ok"):
        return {"ok": False, "status_code": None, "raw": None, "message": "Erro de autenticação OAuth."}
    access_token = token_response.get("access_token")

    url = "https://sandbox-erede.useredecloud.com.br/v1/transactions/notification-URL"
    body = {"URL": callback_url}

    try:
        # 2. Usar o Bearer Token no header
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json", 
                "Accept": "application/json"
            },
            json=body,
            timeout=30,
        )

        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        return {
            "ok": resp.ok,
            "status_code": resp.status_code,
            "raw": raw,
            "message": raw.get("returnMessage") or raw.get("message") or f"HTTP {resp.status_code}",
        }
    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "raw": None,
            "message": f"Erro ao registrar notification URL no sandbox: {e}",
        }