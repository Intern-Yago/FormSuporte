import os
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from painel.utils.sync_blockunblock import sync_login_to_blockunblock
from painel.access import get_allowed_system_keys # <-- Importar a função de acesso

@receiver(user_logged_in)
def sync_blockunblock_on_login(sender, request, user, **kwargs):
    """
    Sempre que logar no Django, gera/atualiza login no BlockUnblock e salva o token na sessão.
    Não depende da senha digitada: usa a senha SSO fixa do .env.
    """
    # NOVA CHECAGEM: Se não tem acesso ao sistema, ignora.
    if "blockunblock" not in get_allowed_system_keys(user):
        return

    sso_password = os.getenv("BLOCKUNBLOCK_SSO_PASSWORD", "")
    if not sso_password:
        return

    ok, data = sync_login_to_blockunblock(user, sso_password)
    if not ok:
        return

    token = (data or {}).get("data", {}).get("accessToken")
    if token:
        request.session["blockunblock_access_token"] = token