import requests
import logging
import os

logger = logging.getLogger(__name__)


def get_blockunblock_url():
    return os.getenv("BLOCK_UNBLOCK_BASE_URL", "http://127.0.0.1").rstrip("/")


def _get_user_sync_payload(user, password=None):
    profile = getattr(user, "profile", None)
    role = getattr(profile, "role", "colaborador")
    setor = getattr(profile, "setor", "suporte")

    email = (user.email or "").strip()
    if not email:
        email = f"{user.username}@eaata.local"
    print(role, setor)
    payload = {
        "email": email,
        "username": user.username,
        "role": role,
        "setor": setor,
    }

    if password is not None:
        payload["password"] = password

    return payload


def sync_user_password(user, password):
    url = f"{get_blockunblock_url()}/api/v1/sync/user/password"
    payload = _get_user_sync_payload(user, password=password)

    try:
        response = requests.put(url, json=payload, timeout=8)

        if response.status_code == 200:
            logger.info(f"Senha sincronizada com sucesso no BlockUnblock para {payload['email']}")
            return True, response.json()

        logger.error(
            f"Erro ao sincronizar senha para {payload['email']}: "
            f"{response.status_code} - {response.text}"
        )
        return False, response.text

    except Exception as e:
        logger.exception(f"Exceção ao sincronizar senha para {payload['email']}: {e}")
        return False, str(e)


def sync_login_to_blockunblock(user, password):
    url = f"{get_blockunblock_url()}/api/v1/sync/login"
    payload = _get_user_sync_payload(user, password=password)
    email = payload["email"]

    try:
        response = requests.post(url, json=payload, timeout=8)

        if response.status_code in (200, 201):
            logger.info(f"Login sincronizado com sucesso para {email}")
            return True, response.json()

        # tenta autocorrigir senha desencontrada
        if response.status_code == 401:
            logger.warning(
                f"Login no BlockUnblock falhou para {email} com 401. "
                f"Tentando sincronizar senha e repetir login."
            )

            ok_password, password_resp = sync_user_password(user, password)

            if ok_password:
                retry_response = requests.post(url, json=payload, timeout=8)

                if retry_response.status_code in (200, 201):
                    logger.info(
                        f"Login sincronizado com sucesso para {email} "
                        f"após corrigir a senha no BlockUnblock."
                    )
                    return True, retry_response.json()

                logger.error(
                    f"Retry de login falhou para {email}: "
                    f"{retry_response.status_code} - {retry_response.text}"
                )
                return False, retry_response.text

            logger.error(
                f"Não foi possível sincronizar a senha de {email} antes do retry: "
                f"{password_resp}"
            )
            return False, password_resp

        logger.error(f"Erro ao sincronizar login para {email}: {response.status_code} - {response.text}")
        return False, response.text

    except Exception as e:
        logger.exception(f"Exceção ao sincronizar login para {email}: {e}")
        return False, str(e)


def sync_user_creation(user, password):
    url = f"{get_blockunblock_url()}/api/v1/sync/user"
    payload = _get_user_sync_payload(user, password=password)

    try:
        response = requests.post(url, json=payload, timeout=8)
        return response.status_code in (200, 201)
    except Exception as e:
        logger.exception(f"Erro ao sincronizar criação de usuário {payload['email']}: {e}")
        return False


def sync_user_update(user):
    url = f"{get_blockunblock_url()}/api/v1/sync/user/role"
    payload = _get_user_sync_payload(user)

    payload = {
        "email": payload["email"],
        "role": payload["role"],
        "setor": payload["setor"],
    }

    try:
        response = requests.put(url, json=payload, timeout=8)
        return response.status_code == 200
    except Exception as e:
        logger.exception(f"Erro ao sincronizar atualização de usuário {payload['email']}: {e}")
        return False


def sync_user_deactivation(user):
    url = f"{get_blockunblock_url()}/api/v1/sync/user/deactivate"
    payload = _get_user_sync_payload(user)

    try:
        response = requests.post(url, json={"email": payload["email"]}, timeout=8)
        return response.status_code == 200
    except Exception as e:
        logger.exception(f"Erro ao sincronizar desativação de usuário {payload['email']}: {e}")
        return False