from django.conf import settings
from .access import get_allowed_systems

def painel_modules(request):
    mapping = getattr(settings, 'PAINEL_MODULE_AREAS', {})
    systems_allowed = get_allowed_systems(request.user)

    name_map = {
        'ocorrencia_erro': 'Ocorrências',
        'situacao_veiculo': 'Situação (Serial)',
        'simulador': 'Simulador',
        'serial_vci': 'Seriais VCI',
        'form': 'Form (Veículos)',
        'pedido': 'Pedidos',
        'API': 'API',
    }

    modules = []
    for app_label, setor in mapping.items():
        name = name_map.get(app_label, app_label.replace('_', ' ').title())
        url = f"/admin/{app_label}/"
        modules.append({
            "app": app_label,
            "name": name,
            "url": url,
            "setor": setor
        })

    profile = None
    role = None
    setor = None

    if getattr(request, 'user', None) and request.user.is_authenticated:
        profile = getattr(request.user, 'profile', None)
        if profile:
            role = profile.role
            setor = profile.setor

    if not (getattr(request, 'user', None) and request.user.is_authenticated):
        allowed = []
    else:
        if request.user.is_superuser or role in ('dono', 'diretor', 'ti'):
            allowed = modules
        elif role == 'gestor' and setor:
            allowed = [m for m in modules if m['setor'] == setor]
        else:
            allowed = []

    is_gestor_ti = bool(role == 'gestor' and setor == 'ti')

    return {
        'admin_modules': modules,
        'allowed_admin_modules': allowed,
        'user_role': role,
        'user_setor': setor,
        'user_area': getattr(profile, 'area', None),
        'is_gestor_ti': is_gestor_ti,
        'PAINEL_MODULE_AREAS': mapping,
        'systems_allowed': systems_allowed,
        'allowed_systems_ids': [s.get('id') for s in systems_allowed],
    }