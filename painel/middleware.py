from django.shortcuts import redirect
from django.urls import reverse
from django.conf import settings
from .access import get_allowed_system_keys

class PainelAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or "/"

        systems = getattr(settings, "PAINEL_SYSTEMS", {})

        # Se bater em prefixo de um sistema, valida acesso
        for key, cfg in systems.items():
            # O sistema 'simulador' e a 'api' são acessíveis via token ou publicamente (o front),
            # por isso pulamos a verificação de permissão de SETOR do painel aqui.
            if key in ('api', 'simulador'):
                continue

            prefix = cfg.get("url") or ""
            if prefix and path.startswith(prefix):
                allowed = get_allowed_system_keys(request.user)
                if key not in allowed:
                    return redirect("painel_dashboard")

        return self.get_response(request)

class LoginRequiredMiddleware:
    """
    Exige autenticação para todas as rotas, exceto uma lista de URLs isentas.
    Redireciona usuários anônimos para o painel (home) para login.
    """

    EXEMPT_PREFIXES = (
        '/painel/',              # painel e painel/logout
        '/static/', '/staticfiles/', '/media/',  # assets
        '/api/',                 # API endpoints
        '/webhooks/',            # Webhooks públicos
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user = getattr(request, 'user', None)

        # Permite acessar somente a raiz (/) sem login para exibir o painel de login
        if path == '/':
            return self.get_response(request)

        # Demais caminhos: somente os explicitamente isentos (assets e /painel/)
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return self.get_response(request)

        # Se está autenticado, segue
        if user and user.is_authenticated:
            return self.get_response(request)

        # Caso contrário, redireciona para painel (home)
        return redirect('painel_home')


class AdminAreaAccessMiddleware:
    """
    Restringe acesso ao Django Admin por área para usuários com papel 'gestor'.
    - Dono/Diretor/TI e superusuário: acesso total.
    - Gestor: apenas apps do admin pertencentes à sua área.
    - Colaborador: sem acesso ao admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        user = getattr(request, 'user', None)

        if not (path.startswith('/admin/')):
            return self.get_response(request)

        # Exceções comuns do admin (login, static, logout) - delega para LoginRequiredMiddleware
        if path.startswith('/admin/login') or path.startswith('/admin/logout') or path.startswith('/admin/js'):
            return self.get_response(request)

        # Não autenticado já será redirecionado pelo LoginRequired
        if not (user and user.is_authenticated):
            return self.get_response(request)

        # Superuser tem acesso total
        if user.is_superuser:
            return self.get_response(request)

        profile = getattr(user, 'profile', None)
        role = getattr(profile, 'role', None)
        setor_user = getattr(profile, 'setor', None)

        # Dono/Diretor/TI tem acesso total
        if role in ('dono', 'diretor', 'ti'):
            return self.get_response(request)

        # Colaborador: bloqueia admin
        if role == 'colaborador':
            return redirect('painel_dashboard')

        # Gestor: pode abrir a home do admin e só os apps da área
        if role == 'gestor':
            # permitir a página inicial do admin
            if path.rstrip('/') == '/admin':
                return self.get_response(request)

            # caminho /admin/<app_label>/...
            segments = [seg for seg in path.split('/') if seg]
            app_label = segments[1] if len(segments) > 1 else None
            from django.conf import settings
            mapping = getattr(settings, 'PAINEL_MODULE_AREAS', {})
            app_setor = mapping.get(app_label)
            if app_setor and setor_user == app_setor:
                return self.get_response(request)
            # bloqueia
            return redirect('painel_dashboard')

        # padrão: segue
        return self.get_response(request)
