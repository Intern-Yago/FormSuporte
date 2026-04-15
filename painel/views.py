import os
from time import time
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User, Group, Permission
from django.db.models import Count, Q
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from urllib.parse import urlencode, quote

from urllib3 import request
from django.urls import reverse

from Form_Suporte import settings
from clientes.integrations.odoo_client import OdooClient, OdooConfig
from painel.decorators import require_system_access

from ocorrencia_erro.models import Country, CountryPermission, Record
from simulador.models import Registro
from pedido.models import Venda
from situacao_veiculo.models import SerialSearchLog

from .access import get_allowed_systems, get_allowed_system_keys
from usuarios.models import UsuarioProfile
from .utils.sync_blockunblock import (
    sync_login_to_blockunblock,
    sync_user_creation,
    sync_user_update,
    sync_user_deactivation,
	sync_user_password
)

import os
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from django.utils.http import url_has_allowed_host_and_scheme

import json

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("blockunblock")
def sso_blockunblock(request):
    access = request.session.get("blockunblock_access_token")
    refresh = request.session.get("blockunblock_refresh_token")
    user_data = request.session.get("blockunblock_user")

    if not access:
        return redirect("painel_dashboard")

    blockunblock_frontend_url = getattr(
		settings,
		"BLOCK_UNBLOCK_FRONTEND_URL",
		"https://seu-blockunblock.com"
	).rstrip("/")

    params = {
        "accessToken": access,
        "refreshToken": refresh or "",
        "user": json.dumps(user_data or {}),
    }

    return redirect(f"{blockunblock_frontend_url}/sso.html?{urlencode(params)}")

def _odoo_client() -> OdooClient:
    cfg = OdooConfig(
        url=settings.ODOO_URL,
        db=settings.ODOO_DB,
        username=settings.ODOO_USER,
        password=settings.ODOO_PASSWORD,
    )
    return OdooClient(cfg)

def home(request):
	if request.method == 'POST':
		login_input = (request.POST.get('username') or '').strip().lower()
		password = request.POST.get('password', '')

		# 1) tenta por e-mail
		user_obj = User.objects.filter(email__iexact=login_input).first()
		if user_obj:
			user = authenticate(request, username=user_obj.username, password=password)
		else:
			# 2) fallback: tenta por username
			user = authenticate(request, username=login_input, password=password)

		if user is not None:
			login(request, user)

			# SSO BlockUnblock
			if "blockunblock" in get_allowed_system_keys(user):
				ok, resp = sync_login_to_blockunblock(user, password)
				if ok and isinstance(resp, dict):
					payload = resp.get("data") or {}
					access = payload.get("accessToken")
					refresh = payload.get("refreshToken")
					block_user = payload.get("user")
					
					if access:
						request.session["blockunblock_access_token"] = access
					if refresh:
						request.session["blockunblock_refresh_token"] = refresh
					if block_user:
						request.session["blockunblock_user"] = block_user
				else:
					print(request, f"SSO BlockUnblock falhou: {resp}")

			# redirect com next
			next_url = request.POST.get("next") or request.GET.get("next")

			if next_url and url_has_allowed_host_and_scheme(
				next_url,
				allowed_hosts={request.get_host()},
				require_https=request.is_secure(),
			):
				return redirect(next_url)

			return redirect('painel_dashboard')


	if request.user.is_authenticated:
		return redirect('painel_dashboard')

	return render(request, 'painel/index.html')


def sair(request):
	logout(request)
	return redirect('painel_home')

@login_required(login_url=settings.URL_LOGIN)
def dashboard(request):
    """Dashboard com os módulos permitidos."""
    systems = get_allowed_systems(request.user)

    # Normaliza chaves pro template dashboard.html
    quick_links = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "url": s.get("url"),
            "sector": s.get("setor") or s.get("sector") or "geral",
        }
        for s in systems
    ]

	# =========================================================
    # INJEÇÃO DINÂMICA DOS CARDS DE KPI (ROTAS FIXAS)
    # =========================================================
    profile = getattr(request.user, 'profile', None)
    role = getattr(profile, 'role', None) if profile else None
    setor = getattr(profile, 'setor', None) if profile else None

    # Verifica se é Master (Dono, Diretor ou TI)
    is_master = request.user.is_superuser or role in ['dono', 'diretor'] or setor == 'ti'
    
    setores_kpi = {
        'suporte': 'kpis:dashboard_suporte',
        'comercial': 'kpis:dashboard_comercial',
    }

    if is_master:
        for s, url_name in setores_kpi.items():
            quick_links.append({
                "id": f"kpi_{s}",
                "name": f"KPIs {s.title()}",
                "url": reverse(url_name),
                "sector": s
            })
            
    # AQUI ESTÁ A CORREÇÃO: Somente GESTORES entram nessa regra agora!
    elif role == 'gestor':
        if setor in setores_kpi:
            quick_links.append({
                "id": f"kpi_{setor}",
                "name": f"KPIs {setor.title()}",
                "url": reverse(setores_kpi[setor]),
                "sector": setor
            })

    # =========================================================
    # REORDENAR A LISTA PARA O HTML AGRUPAR CORRETAMENTE
    # =========================================================
    quick_links = sorted(quick_links, key=lambda x: str(x.get("sector", "geral")).strip().lower())

    return render(request, "painel/dashboard.html", {"quick_links": quick_links})

@login_required(login_url=settings.URL_LOGIN)
def settings_view(request):
	"""Configurações de conta: alterar senha."""
	if request.method == 'POST':
		form = PasswordChangeForm(request.user, request.POST)
		if form.is_valid():
			user = form.save()
			update_session_auth_hash(request, user)
            
            # Só sincroniza se tiver acesso
			if "blockunblock" in get_allowed_system_keys(user):
				ok, resp = sync_user_password(user, form.cleaned_data["new_password1"])
				if not ok:
					print(f"Falha ao sincronizar senha no BlockUnblock: {resp}")
            
				print(request, 'Senha alterada com sucesso!')
			return redirect('painel_settings')
		
		else:
			print(request, 'Verifique os erros abaixo.')
	else:
		form = PasswordChangeForm(request.user)

	return render(request, 'painel/settings.html', {'form': form})


def _get_my_profile(request):
	"""
	Helper seguro: devolve (profile, role, setor).
	Se não existir profile ainda, retorna None.
	"""
	profile = getattr(request.user, 'profile', None)
	role = getattr(profile, 'role', None)
	setor = getattr(profile, 'setor', None)
	return profile, role, setor

def _is_dono(user):
	profile = getattr(user, 'profile', None)
	return bool(user.is_superuser or getattr(profile, 'role', None) == 'dono')


def _is_diretor(user):
	profile = getattr(user, 'profile', None)
	return bool(getattr(profile, 'role', None) == 'diretor')


def _is_gestor_ti(user):
	profile = getattr(user, 'profile', None)
	return bool(
		getattr(profile, 'role', None) == 'gestor'
		and getattr(profile, 'setor', None) == 'ti'
	)


def _is_gestor_outro_setor(user):
	profile = getattr(user, 'profile', None)
	return bool(
		getattr(profile, 'role', None) == 'gestor'
		and getattr(profile, 'setor', None)
		and getattr(profile, 'setor', None) != 'ti'
	)


def _is_colaborador_ti(user):
	profile = getattr(user, 'profile', None)
	return bool(
		getattr(profile, 'role', None) == 'colaborador'
		and getattr(profile, 'setor', None) == 'ti'
	)


def _can_create_users(user):
	return (
		_is_dono(user)
		or _is_diretor(user)
		or _is_gestor_ti(user)
		or _is_gestor_outro_setor(user)
	)


def _can_manage_all_users(user):
	return _is_dono(user) or _is_diretor(user) or _is_gestor_ti(user)


def _allowed_roles_to_create(user):
	if _is_dono(user):
		return ['dono', 'diretor', 'gestor', 'colaborador']
	if _is_diretor(user):
		return ['diretor', 'gestor', 'colaborador']
	if _is_gestor_ti(user):
		return ['gestor', 'colaborador']
	if _is_gestor_outro_setor(user):
		return ['colaborador']
	return []


def _allowed_setores_to_create(user, target_role):
	profile = getattr(user, 'profile', None)
	meu_setor = getattr(profile, 'setor', None)

	if _is_dono(user) or _is_diretor(user) or _is_gestor_ti(user):
		if target_role in ('dono', 'diretor'):
			return []
		return ['marketing', 'financeiro', 'suporte', 'ti', 'comercial']

	if _is_gestor_outro_setor(user):
		return [meu_setor] if meu_setor else []

	return []


def _apply_role_flags(user_obj, role, setor=None):
    if role in ('dono', 'diretor'):
        user_obj.is_staff = True
        user_obj.is_superuser = True

    elif role == 'gestor' and setor == 'ti':
        user_obj.is_staff = True
        user_obj.is_superuser = False

    elif role == 'colaborador' and setor == 'ti':
        user_obj.is_staff = True
        user_obj.is_superuser = False

    elif role == 'gestor' and setor == 'comercial':
        user_obj.is_staff = True
        user_obj.is_superuser = False

    else:
        user_obj.is_staff = False
        user_obj.is_superuser = False


def _sync_base_group(user_obj, role):
	base_groups = ['Dono', 'Diretor', 'Gestor', 'Colaborador']
	user_obj.groups.remove(*Group.objects.filter(name__in=base_groups))

	group_name = {
		'dono': 'Dono',
		'diretor': 'Diretor',
		'gestor': 'Gestor',
		'colaborador': 'Colaborador',
	}.get(role)

	if group_name:
		group, _ = Group.objects.get_or_create(name=group_name)
		user_obj.groups.add(group)

@login_required(login_url=settings.URL_LOGIN)
def user_create(request):
	"""
	Cadastro de usuário com hierarquia + setor.

	Regras:
	- Superuser ou (dono/diretor/ti): cria qualquer papel; setor opcional p/ dono/diretor.
	- Gestor: só cria COLABORADOR e o setor é SEMPRE o setor do gestor (forçado no backend).
	- Se criar COLABORADOR do setor SUPORTE, habilita bloco de:
	  - tipo_usuario (responsavel|reporte|semi_admin)
	  - paises_responsavel (lista de países)
	  E isso é salvo via:
	  - Group (tipo técnico)
	  - CountryPermission (permissões por país)
	"""
	from django.conf import settings
	from django.contrib.auth.models import User, Group, Permission
	from django.shortcuts import render, redirect
	from django.contrib import messages
	from django.utils.text import slugify
	import random
	from usuarios.models import UsuarioProfile
	from ocorrencia_erro.models import Country

	# ==========================================================
	# Perfil de quem está criando
	# ==========================================================
	profile = getattr(request.user, 'profile', None)
	role_me = getattr(profile, 'role', None)
	setor_me = getattr(profile, 'setor', None)

	if not _can_create_users(request.user):
		return redirect('painel_dashboard')

	role_labels = {
		'dono': 'Dono',
		'diretor': 'Diretor',
		'gestor': 'Gestor',
		'colaborador': 'Colaborador',
	}
	setor_labels = {
		'marketing': 'Marketing',
		'financeiro': 'Financeiro',
		'suporte': 'Suporte',
		'ti': 'TI',
		'comercial': 'Comercial',
	}

	allowed_roles = _allowed_roles_to_create(request.user)

	if _is_gestor_outro_setor(request.user):
		context_roles = [('colaborador', 'Colaborador')]
		context_setores = [(setor_me, setor_labels.get(setor_me, setor_me.title()))]
		can_choose_role_setor = False
	else:
		context_roles = [(r, role_labels[r]) for r in allowed_roles]
		context_setores = [(k, v) for k, v in setor_labels.items()]
		can_choose_role_setor = True
	
	context = {
		"show_suporte_legacy": False,
		"paises": Country.objects.all().order_by("name"),
		"roles": context_roles,
		"setores": context_setores,
		"can_choose_role_setor": can_choose_role_setor,
		"user_role": role_me,
		"user_setor": setor_me,
		"grupos_comerciais": UsuarioProfile.GrupoComercial.choices,
		"show_comercial_group": False,
		"areas_suporte": UsuarioProfile.AreaSuporte.choices,
	}

	role_selected = request.POST.get("role") or ""
	setor_selected = request.POST.get("setor") or ""

	if _is_gestor_outro_setor(request.user) and setor_me == "comercial":
		context["show_comercial_group"] = True

	if can_choose_role_setor and role_selected == "colaborador" and setor_selected == "comercial":
		context["show_comercial_group"] = True

	if request.method == 'POST':
		nome = (request.POST.get('nome') or '').strip()
		senha = (request.POST.get('senha') or '').strip()
		cpf_cnpj = (request.POST.get('cpf_cnpj') or '').strip()
		contato = (request.POST.get('contato') or '').strip()
		area = (request.POST.get('area') or '').strip()
		email = (request.POST.get('email') or '').strip().lower()
		grupo_comercial = (request.POST.get('grupo_comercial') or '').strip()

		if _is_gestor_outro_setor(request.user):
			role = 'colaborador'
			setor = setor_me
		else:
			role = (request.POST.get('role') or '').strip()
			setor = (request.POST.get('setor') or '').strip()

		if not nome:
			context['error'] = 'Nome é obrigatório.'
			return render(request, 'painel/user_create.html', context)

		if not senha:
			context['error'] = 'Senha é obrigatória.'
			return render(request, 'painel/user_create.html', context)

		if not email:
			context['error'] = 'E-mail é obrigatório (será o login).'
			return render(request, 'painel/user_create.html', context)

		if User.objects.filter(email__iexact=email).exists():
			context['error'] = 'Já existe um usuário com esse e-mail.'
			return render(request, 'painel/user_create.html', context)

		if role not in allowed_roles:
			context['error'] = 'Você não pode criar este tipo de usuário.'
			return render(request, 'painel/user_create.html', context)

		if role in ('dono', 'diretor'):
			setor_value = None
		else:
			allowed_setores = _allowed_setores_to_create(request.user, role)
			if setor not in allowed_setores:
				context['error'] = 'Você não pode criar usuário para este setor.'
				return render(request, 'painel/user_create.html', context)
			setor_value = setor

		base_username = (email.split('@')[0] if email else slugify(nome)) or 'user'
		username = base_username
		while User.objects.filter(username=username).exists():
			username = f"{base_username}{random.randint(10, 99)}"

		user = User.objects.create_user(username=username, email=email, password=senha)
		user.first_name = nome

		_apply_role_flags(user, role, setor_value)
		user.save()

		try:
			_sync_base_group(user, role)
		except Exception:
			pass

		profile, _ = UsuarioProfile.objects.get_or_create(user=user)
		profile.role = role
		profile.setor = setor_value
		profile.grupo_comercial = grupo_comercial
		profile.area = area or None
		profile.cpf_cnpj = cpf_cnpj or None
		profile.contato = contato or None
		profile.save()

		try:
			odoo = _odoo_client()

			vendedor_odoo = odoo.buscar_ou_criar_vendedor(
				nome,
				email=email,
				odoo_user_id=profile.odoo_user_id,
			)

			if vendedor_odoo and vendedor_odoo.get("id"):
				profile.odoo_user_id = vendedor_odoo["id"]
				profile.save(update_fields=["odoo_user_id"])

		except Exception as e:
			messages.warning(
				request,
				f'Usuário criado localmente, mas houve falha ao criar vendedor no Odoo: {e}'
			)

		if role == "colaborador" and setor_value == "suporte":
			from ocorrencia_erro.models import CountryPermission

			tipo_usuario = (request.POST.get("tipo_usuario") or "responsavel").strip()

			if tipo_usuario == "responsavel":
				nome_grupo_tecnico = "Técnicos responsáveis"
			elif tipo_usuario == "reporte":
				nome_grupo_tecnico = "Técnicos de reporte"
			elif tipo_usuario == "semi_admin":
				nome_grupo_tecnico = "Semi Admin"
			else:
				nome_grupo_tecnico = "Técnicos responsáveis"

			grupos_tecnicos = ["Técnicos responsáveis", "Técnicos de reporte", "Semi Admin"]
			user.groups.remove(*Group.objects.filter(name__in=grupos_tecnicos))

			grupo_tecnico, _ = Group.objects.get_or_create(name=nome_grupo_tecnico)
			user.groups.add(grupo_tecnico)

			paises_ids = request.POST.getlist("paises_responsavel")
			paises_ids = [int(x) for x in paises_ids if str(x).isdigit()]

			CountryPermission.objects.filter(user=user).delete()
			for pid in paises_ids:
				try:
					country = Country.objects.get(id=pid)
					CountryPermission.objects.get_or_create(user=user, country=country)
				except Country.DoesNotExist:
					continue

		if role == 'gestor' and setor_value:
			mapping = getattr(settings, 'PAINEL_MODULE_AREAS', {})
			app_labels = [app for app, a in mapping.items() if a == setor_value]
			if app_labels:
				perms = Permission.objects.filter(content_type__app_label__in=app_labels)
				user.user_permissions.add(*list(perms))

		if role == 'gestor' and setor_value == 'comercial':
			from django.contrib.auth.models import Permission

			app_labels = ['pedido', 'simulador']  # seus apps do comercial

			perms = Permission.objects.filter(
				content_type__app_label__in=app_labels
			)

			user.user_permissions.add(*perms)

		if setor_value == 'ti':
			from django.contrib.auth.models import Permission

			perms = Permission.objects.all()
			user.user_permissions.add(*perms)
		user.profile = profile
		
		# Puxa a lista RESTRITA baseada no Dashboard
		sistemas_permitidos = [s.get("id") for s in get_allowed_systems(user) if s.get("id")]

		# Sincroniza criação com BlockUnblock APENAS se o sistema estiver liberado
		if "blockunblock" in sistemas_permitidos:
			sync_user_creation(user, senha)

		messages.success(request, f'Usuário criado com sucesso! Login: {email}')
		return redirect('painel_dashboard')

	return render(request, 'painel/user_create.html', context)

# ======================================================================
#  USUÁRIOS (GESTOR/ADMIN)
# ======================================================================
@login_required(login_url=settings.URL_LOGIN)
def user_manage(request):
	from django.conf import settings

	profile, role_me, setor_me = _get_my_profile(request)

	is_master = _can_manage_all_users(request.user)
	is_gestor = _is_gestor_outro_setor(request.user)

	if not (is_master or is_gestor):
		return redirect('painel_dashboard')

	if is_master:
		qs = User.objects.filter(
			is_active=True
		).annotate(
			search_count=Count('serial_searches', distinct=True),
			venda_count=Count('vendas', distinct=True)
		).select_related('profile').order_by('first_name', 'username')
	else:
		qs = User.objects.filter(
			is_active=True,
			profile__setor=setor_me,
			profile__role='colaborador'
		).exclude(id=request.user.id).annotate(
			search_count=Count('serial_searches', distinct=True),
			venda_count=Count('vendas', distinct=True)
		).select_related('profile').order_by('first_name', 'username')

	for u in qs:
		grupos = set(u.groups.values_list("name", flat=True))
		if "Técnicos de reporte" in grupos:
			u.tipo_usuario_atual = "reporte"
		elif "Semi Admin" in grupos:
			u.tipo_usuario_atual = "semi_admin"
		else:
			u.tipo_usuario_atual = "responsavel"

		u.paises_ids_csv = ",".join(
			str(pid) for pid in u.country_permissions.values_list("country_id", flat=True)
		)

	context = {
		"users_list": qs,
		"is_master": is_master,
		"setor_me": setor_me,
		"paises": Country.objects.all().order_by("name"),
		"grupos_comerciais": UsuarioProfile.GrupoComercial.choices,
		"areas_suporte": UsuarioProfile.AreaSuporte.choices,
	}

	if is_master:
		systems_cfg = getattr(settings, "PAINEL_SYSTEMS", {})
		systems_list = [{"id": k, "name": v.get("name")} for k, v in systems_cfg.items()]

		overrides = {}
		for u in qs:
			p = getattr(u, "profile", None)

			default_links = get_allowed_systems(u)
			default_ids = [item.get("id") for item in default_links if item.get("id")]

			extra_ids = getattr(p, "allowed_systems", []) or []

			merged_ids = sorted(set(default_ids) | set(extra_ids))
			overrides[u.id] = merged_ids

		context["systems_list"] = systems_list
		context["user_overrides"] = overrides

	return render(request, 'painel/user_manage.html', context)

@require_POST
@login_required(login_url=settings.URL_LOGIN)
def user_delete(request, user_id):
	is_master = _can_manage_all_users(request.user)
	is_gestor = _is_gestor_outro_setor(request.user)

	if not (is_master or is_gestor):
		return JsonResponse({
			"ok": False,
			"message": "Você não tem permissão para excluir este usuário."
		}, status=403)

	target = get_object_or_404(User, id=user_id)

	if is_gestor:
		_, _, setor_me = _get_my_profile(request)
		if not hasattr(target, 'profile') or target.profile.role != 'colaborador' or target.profile.setor != setor_me:
			return JsonResponse({
				"ok": False,
				"message": "Você não tem permissão para excluir este usuário."
			}, status=400)

	# se já está desativado, só avisa
	if not target.is_active:
		return JsonResponse({
			"ok": False,
			"message": f'O usuário "{target.username}" já está desativado.'
		}, status=400)

	target.is_active = False
	target.save(update_fields=['is_active'])
	
	# Puxa a lista RESTRITA baseada no Dashboard
	sistemas_permitidos = [s.get("id") for s in get_allowed_systems(target) if s.get("id")]

	# Sincroniza desativação com BlockUnblock
	if "blockunblock" in sistemas_permitidos:
		sync_user_deactivation(target)
	
	return JsonResponse({
		"ok": True,
		"message": f'Usuário "{target.username}" desativado com sucesso.'
	})



@require_POST
@login_required(login_url=settings.URL_LOGIN)
def user_set_password(request, user_id):
    is_master = _can_manage_all_users(request.user)
    is_gestor = _is_gestor_outro_setor(request.user)

    if not (is_master or is_gestor):
        return JsonResponse({
            "ok": False,
            "message": "Você não tem permissão para alterar a senha deste usuário."
        }, status=403)

    if is_gestor:
        _, _, setor_me = _get_my_profile(request)
        target = get_object_or_404(
            User.objects.select_related('profile'),
            id=user_id,
            is_active=True,
            profile__role='colaborador',
            profile__setor=setor_me
        )
    else:
        target = get_object_or_404(
            User.objects.select_related('profile'),
            id=user_id,
            is_active=True
        )

    p1 = (request.POST.get('new_password1') or '').strip()
    p2 = (request.POST.get('new_password2') or '').strip()

    if not p1 or not p2:
        return JsonResponse({
            "ok": False,
            "message": "Informe a nova senha e a confirmação."
        }, status=400)

    if p1 != p2:
        return JsonResponse({
            "ok": False,
            "message": "As senhas não coincidem."
        }, status=400)

    try:
        validate_password(p1, user=target)
    except ValidationError as e:
        return JsonResponse({
            "ok": False,
            "message": "Senha inválida: " + " ".join(e.messages)
        }, status=400)

    target.set_password(p1)
    target.save()

    sistemas_permitidos = [s.get("id") for s in get_allowed_systems(target) if s.get("id")]

    if "blockunblock" in sistemas_permitidos:
        try:
            from .utils.sync_blockunblock import sync_user_password
            sync_user_password(target, p1)
        except Exception as e:
            return JsonResponse({
                "ok": False,
                "message": f"Senha alterada no Django, mas falhou sincronização com BlockUnblock: {e}"
            }, status=400)

    return JsonResponse({
        "ok": True,
        "message": f'Senha de "{target.username}" alterada com sucesso.'
    })



@require_POST
@login_required(login_url=settings.URL_LOGIN)
def user_update(request, user_id):
	from ocorrencia_erro.models import Country, CountryPermission

	is_master = _can_manage_all_users(request.user)
	is_gestor = _is_gestor_outro_setor(request.user)

	if not (is_master or is_gestor):
		return JsonResponse({
			"ok": False,
			"message": "Você não tem permissão para editar este usuário."
		}, status=403)

	if is_gestor:
		_, _, setor_me = _get_my_profile(request)
		target = get_object_or_404(
			User.objects.select_related("profile"),
			id=user_id,
			profile__setor=setor_me,
			profile__role='colaborador'
		)
	else:
		target = get_object_or_404(
			User.objects.select_related("profile"),
			id=user_id
		)

	email = (request.POST.get('email') or '').strip().lower()
	cpf_cnpj = (request.POST.get('cpf_cnpj') or '').strip()
	contato = (request.POST.get('contato') or '').strip()
	area_resp = (request.POST.get('area') or '').strip()

	new_role = (request.POST.get('role') or '').strip() if is_master else None
	new_setor = (request.POST.get('setor') or '').strip() if is_master else None

	grupo_comercial = (request.POST.get('grupo_comercial') or '').strip()
	tipo_usuario = (request.POST.get('tipo_usuario') or 'responsavel').strip()
	paises_ids = request.POST.getlist("paises_responsavel")
	paises_ids = [int(x) for x in paises_ids if str(x).isdigit()]

	if email:
		exists = User.objects.filter(email__iexact=email).exclude(id=target.id).exists()
		if exists:
			return JsonResponse({
				"ok": False,
				"message": "Já existe outro usuário com esse e-mail."
			}, status=400)

	target.email = email or ""
	target.save(update_fields=['email'])

	p, _ = UsuarioProfile.objects.get_or_create(user=target)
	updates = []

	p.cpf_cnpj = cpf_cnpj or None
	updates.append("cpf_cnpj")

	p.contato = contato or None
	updates.append("contato")

	p.area = area_resp or None
	updates.append("area")

	final_role = p.role
	final_setor = p.setor

	if is_master:
		allowed_roles = _allowed_roles_to_create(request.user)

		if new_role:
			if new_role not in allowed_roles:
				return JsonResponse({
					"ok": False,
					"message": "Você não pode definir esse cargo para este usuário."
				}, status=400)
			final_role = new_role

		if final_role in ('dono', 'diretor'):
			final_setor = None
		else:
			allowed_setores = ['marketing', 'financeiro', 'suporte', 'ti', 'comercial']
			if new_setor not in allowed_setores:
				return JsonResponse({
					"ok": False,
					"message": "Setor inválido."
				}, status=400)
			final_setor = new_setor

		p.role = final_role
		p.setor = final_setor
		updates.extend(["role", "setor"])

		_apply_role_flags(target, final_role, final_setor)
		target.save(update_fields=['is_staff', 'is_superuser'])

		target.user_permissions.clear()

		if final_setor == 'ti':
			perms = Permission.objects.all()
			target.user_permissions.add(*perms)

		elif final_role == 'gestor' and final_setor == 'comercial':
			perms = Permission.objects.filter(
				content_type__app_label__in=['pedido', 'simulador']
			)
			target.user_permissions.add(*perms)

		elif final_role == 'gestor' and final_setor:
			mapping = getattr(settings, 'PAINEL_MODULE_AREAS', {})
			app_labels = [app for app, a in mapping.items() if a == final_setor]
			if app_labels:
				perms = Permission.objects.filter(content_type__app_label__in=app_labels)
				target.user_permissions.add(*list(perms))

		try:
			_sync_base_group(target, final_role)
		except Exception:
			pass

	# ===== grupo comercial =====
	if final_role == 'colaborador' and final_setor == 'comercial':
		valid_grupos = [v for v, _ in UsuarioProfile.GrupoComercial.choices]
		if grupo_comercial and grupo_comercial not in valid_grupos:
			return JsonResponse({
				"ok": False,
				"message": "Grupo comercial inválido."
			}, status=400)

		p.grupo_comercial = grupo_comercial or None
		updates.append("grupo_comercial")
	else:
		if hasattr(p, "grupo_comercial"):
			p.grupo_comercial = None
			updates.append("grupo_comercial")

	# ===== extras suporte =====
	if final_role == 'colaborador' and final_setor == 'suporte':
		if tipo_usuario == "responsavel":
			nome_grupo_tecnico = "Técnicos responsáveis"
		elif tipo_usuario == "reporte":
			nome_grupo_tecnico = "Técnicos de reporte"
		elif tipo_usuario == "semi_admin":
			nome_grupo_tecnico = "Semi Admin"
		else:
			nome_grupo_tecnico = "Técnicos responsáveis"

		grupos_tecnicos = ["Técnicos responsáveis", "Técnicos de reporte", "Semi Admin"]
		target.groups.remove(*Group.objects.filter(name__in=grupos_tecnicos))

		grupo_tecnico, _ = Group.objects.get_or_create(name=nome_grupo_tecnico)
		target.groups.add(grupo_tecnico)

		CountryPermission.objects.filter(user=target).delete()
		for pid in paises_ids:
			try:
				country = Country.objects.get(id=pid)
				CountryPermission.objects.get_or_create(user=target, country=country)
			except Country.DoesNotExist:
				continue
	else:
		grupos_tecnicos = ["Técnicos responsáveis", "Técnicos de reporte", "Semi Admin"]
		target.groups.remove(*Group.objects.filter(name__in=grupos_tecnicos))
		CountryPermission.objects.filter(user=target).delete()

	if updates:
		p.save(update_fields=list(dict.fromkeys(updates)))

	# Atualiza o perfil na memória e recalcula os acessos visuais
	target.profile = p
	sistemas_permitidos = [s.get("id") for s in get_allowed_systems(target) if s.get("id")]

	if "blockunblock" in sistemas_permitidos:
		sync_user_update(target)
	else:
		# Se ele perdeu acesso na edição, desativa lá!
		sync_user_deactivation(target)

	return JsonResponse({
		"ok": True,
		"message": f'Dados de "{target.username}" alterados com sucesso.'
	})

@require_POST
@login_required(login_url=settings.URL_LOGIN)
def user_update_systems(request, user_id):
    profile, role_me, setor_me = _get_my_profile(request)

    is_master = _can_manage_all_users(request.user)

    if not is_master:
        return JsonResponse({
            "ok": False,
            "message": "Sem permissão para alterar acessos."
        }, status=403)

    target = get_object_or_404(
        User.objects.select_related('profile'),
        id=user_id,
        is_active=True
    )

    target_profile = getattr(target, "profile", None)
    if not target_profile:
        return JsonResponse({
            "ok": False,
            "message": "Perfil do usuário não encontrado."
        }, status=404)

 	# 1. Checa se ele TINHA acesso antes de salvar
    sistemas_antigos = [s.get("id") for s in get_allowed_systems(target) if s.get("id")]
    old_access = "blockunblock" in sistemas_antigos

    selected = request.POST.getlist("systems[]")
    selected = sorted(set(s.strip() for s in selected if s.strip()))

    target_profile.allowed_systems = selected
    target_profile.save(update_fields=["allowed_systems"])

    # Força a memória a ler a atualização manual que acabou de ser feita
    target.profile = target_profile

    # 2. Checa se ele TEM acesso agora
    sistemas_novos = [s.get("id") for s in get_allowed_systems(target) if s.get("id")]
    new_access = "blockunblock" in sistemas_novos

    # 3. Dispara as ações para manter o BlockUnblock sincronizado com a permissão
    if not old_access and new_access:
        # Ganhou o acesso. Cria o user lá.
        sso_password = os.getenv("BLOCKUNBLOCK_SSO_PASSWORD", "SenhaPadraoTemporaria!")
        sync_user_creation(target, sso_password)
    elif old_access and not new_access:
        # Perdeu o acesso. Desativa lá.
        sync_user_deactivation(target)

    return JsonResponse({
        "ok": True,
        "message": f'Acessos do usuário "{target.username}" atualizados com sucesso.'
    })

@login_required(login_url=settings.URL_LOGIN)
def user_dashboard_stats(request, user_id):
    is_master = _can_manage_all_users(request.user)
    is_gestor = _is_gestor_outro_setor(request.user)

    if not (is_master or is_gestor):
        return JsonResponse({"ok": False, "message": "Sem permissão"}, status=403)

    target = get_object_or_404(User, id=user_id, is_active=True)

    # 1. Ocorrências (Record) - Busca por technical ou responsible (string match)
    query_name = target.first_name or target.username
    ocorrencias = Record.objects.filter(
        Q(technical__icontains=query_name) | Q(responsible__icontains=query_name)
    ).order_by("-data")[:5]

    ocorrencias_data = [{
        "id": o.id,
        "data": o.data.strftime("%d/%m/%Y") if o.data else "-",
        "cliente": o.contact,
        "status": o.get_status_display(),
        "problema": (o.problem_detected[:50] + "...") if o.problem_detected and len(o.problem_detected) > 50 else (o.problem_detected or "-")
    } for o in ocorrencias]

    # 2. Consultas (SerialSearchLog)
    consultas = SerialSearchLog.objects.filter(user=target).order_by("-created_at")[:5]
    consultas_data = [{
        "serial": c.searched_serial,
        "data": c.created_at.strftime("%d/%m/%Y %H:%M")
    } for c in consultas]

    # 3. Orçamentos (Registro)
    orçamentos = Registro.objects.filter(nome_vendedor__icontains=query_name).order_by("-criado_em")[:5]
    orçamentos_data = [{
        "id": r.id,
        "cliente": r.nome_cliente,
        "data": r.criado_em.strftime("%d/%m/%Y"),
        "total": float(r.valor_avista or 0)
    } for r in orçamentos]

    # 4. Pedidos/Vendas (Venda)
    vendas = Venda.objects.filter(vendedor=target).order_by("-criado_em")[:5]
    vendas_data = [{
        "id": v.id,
        "cliente": v.nome_cliente,
        "data": v.criado_em.strftime("%d/%m/%Y"),
        "status": v.get_status_display(),
        "total": float(v.valor_entrada + (getattr(v, 'valor_frete', 0) or 0))
    } for v in vendas]

    return JsonResponse({
        "ok": True,
        "user": {
            "name": target.first_name or target.username,
            "username": target.username,
        },
        "stats": {
            "ocorrencias_total": Record.objects.filter(Q(technical__icontains=query_name) | Q(responsible__icontains=query_name)).count(),
            "consultas_total": SerialSearchLog.objects.filter(user=target).count(),
            "orcamentos_total": Registro.objects.filter(nome_vendedor__icontains=query_name).count(),
            "vendas_total": Venda.objects.filter(vendedor=target).count(),
        },
        "recent": {
            "ocorrencias": ocorrencias_data,
            "consultas": consultas_data,
            "orcamentos": orçamentos_data,
            "vendas": vendas_data
        }
    })