from django.conf import settings


def get_user_profile(user):
    return getattr(user, "profile", None)


def get_user_setor(user):
    profile = get_user_profile(user)
    return getattr(profile, "setor", None)


def get_allowed_system_keys(user):
    if not getattr(user, "is_authenticated", False):
        return set()

    profile = get_user_profile(user)
    role = getattr(profile, "role", None)
    setor = getattr(profile, "setor", None)

    # 1) acesso total
    if user.is_superuser or role in ("dono", "diretor", "ti"):
        return set(getattr(settings, "PAINEL_SYSTEMS", {}).keys())

    # 2) override salvo no profile unificado (Substituição absoluta)
    allowed_systems = getattr(profile, "allowed_systems", None)
    # Verifica com "is not None" para garantir que uma lista vazia [] seja respeitada
    if allowed_systems is not None:
        return set(allowed_systems)

    # 3) regra padrão por setor
    defaults = getattr(settings, "PAINEL_SETOR_DEFAULT_ACCESS", {})
    allowed_setores = defaults.get(setor, set())

    systems = getattr(settings, "PAINEL_SYSTEMS", {})
    out = set()
    for key, cfg in systems.items():
        if cfg.get("setor") in allowed_setores:
            out.add(key)

    return out


def get_allowed_systems(user):
    profile = getattr(user, "profile", None)
    systems_cfg = getattr(settings, "PAINEL_SYSTEMS", {})

    if not user.is_authenticated:
        return []

    role = getattr(profile, "role", None)
    setor = getattr(profile, "setor", None)

    always_open = {"simulador", "pedido"}

    result = []
    added_ids = set()

    def add_system(sid, cfg):
        if not cfg or sid in added_ids:
            return
        result.append({
            "id": sid,
            "name": cfg.get("name"),
            "url": cfg.get("url"),
            "sector": cfg.get("setor") or cfg.get("sector") or "geral",
        })
        added_ids.add(sid)

    # 1) acesso total
    has_full_access = (
        user.is_superuser
        or role in ("dono", "diretor")
        or (role == "gestor" and setor == "ti")
        or (role == "colaborador" and setor == "ti")
    )

    if has_full_access:
        for sid, cfg in systems_cfg.items():
            add_system(sid, cfg)
    else:
        # 2) acessos manuais = substituição completa
        manual_ids = getattr(profile, "allowed_systems", None)
        if manual_ids is not None:
            for sid in manual_ids:
                cfg = systems_cfg.get(sid)
                add_system(sid, cfg)
        else:
            # 3) regra padrão por setor + sistemas liberados para todos
            for sid, cfg in systems_cfg.items():
                system_setor = cfg.get("setor") or cfg.get("sector")

                if sid in always_open:
                    add_system(sid, cfg)
                    continue

                if role in ("gestor", "colaborador") and setor and system_setor == setor:
                    add_system(sid, cfg)

    # ORDENA a lista por setor antes de devolver.
    # Usamos lower() e strip() para evitar que "Suporte" e "suporte" criem grupos separados.
    result = sorted(result, key=lambda x: str(x.get("sector", "geral")).strip().lower())

    return result