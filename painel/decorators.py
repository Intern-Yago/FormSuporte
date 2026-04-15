from functools import wraps
from django.conf import settings
from django.shortcuts import redirect

from .access import get_allowed_systems


def require_system_access(system_id: str):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            # não logado → login
            if not request.user.is_authenticated:
                return redirect(settings.URL_LOGIN)

            allowed_ids = {
                item.get("id")
                for item in get_allowed_systems(request.user)
                if item.get("id")
            }

            # logado, mas sem acesso → painel
            if system_id not in allowed_ids:
                return redirect("painel_home")  # ou "painel_home" se for o nome da sua url

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator