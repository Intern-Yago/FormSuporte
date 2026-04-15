from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse

from painel.decorators import require_system_access
from .forms import VeiculoForm
from .models import Veiculo
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.utils import timezone
from datetime import timedelta, datetime
from django.contrib.contenttypes.models import ContentType
import json
from django.conf import settings
# views.py - Lógica de Negócio para o App 'form'

def check_user_full_permission(user):
    """
    Verifica se o usuário tem permissão total (superuser ou gestor do setor suporte).
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    
    profile = getattr(user, 'profile', None)
    if profile:
        # Dono, Diretor e TI têm acesso total
        if profile.role in ['dono', 'diretor', 'ti']:
            return True
        # Gestor do setor Suporte tem acesso total
        if profile.role == 'gestor' and profile.setor == 'suporte':
            return True
            
    return False

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("form")
def cadastrar_veiculo(request):
    """
    Processa o formulário de cadastro de um novo veículo.
    
    Se a requisição for POST, valida e salva o formulário.
    Caso contrário, exibe um formulário vazio.
    """
    if request.method == 'POST':
        form = VeiculoForm(request.POST)
        if form.is_valid():
            # Salva o novo veículo no banco de dados
            veiculo = form.save()
            
            # Registra no log do admin
            if request.user.is_authenticated:
                LogEntry.objects.log_action(
                    user_id=request.user.id,
                    content_type_id=ContentType.objects.get_for_model(veiculo).pk,
                    object_id=veiculo.pk,
                    object_repr=str(veiculo),
                    action_flag=ADDITION,
                    change_message=json.dumps([{'added': {}}])
                )
                
            # Redireciona para a página de listagem após o sucesso
            return redirect('index_form')
        else:
            # Exibe mensagem de erro se a validação falhar
            print("deu erro")
    else:
        form = VeiculoForm()
    
    # Renderiza o template de criação com o formulário (vazio ou com erros)
    return render(request, 'form/create.html', {'form': form})

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("form")
def index(request):
    """
    Exibe a lista de veículos com suporte a filtros e paginação.
    """
    # Inicializa um objeto Q vazio para construir a consulta de filtros
    query_filters = Q()
    
    # Mapeamento dos parâmetros de filtro da URL para os campos do modelo
    filter_params = {
        'pais': 'pais__icontains',
        'brand': 'brand__icontains',
        'modelo': 'modelo__icontains',
        'ano': 'ano__icontains',
    }
    
    # Aplica os filtros dinamicamente
    for param, field_lookup in filter_params.items():
        value = request.GET.get(param)
        if value:
            # Adiciona a condição de filtro ao objeto Q
            query_filters &= Q(**{field_lookup: value})
    
    # Busca os veículos aplicando os filtros e ordenando por campos chave
    veiculos_filtrados = Veiculo.objects.filter(query_filters).order_by('pais', 'brand', 'modelo', 'ano')

    # --- Paginação ---
    per_page = request.GET.get('per_page', '10')
    if per_page == 'todos':
        # Para "todos", enviamos um objeto que se comporte como uma página única
        paginator = Paginator(object_list=veiculos_filtrados, per_page=max(veiculos_filtrados.count(), 1))
        page_obj = paginator.get_page(1)
    else:
        try:
            per_page_int = int(per_page)
        except:
            per_page_int = 10
        paginator = Paginator(object_list=veiculos_filtrados, per_page=per_page_int)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
    
    # Verifica se o usuário tem permissão total (superuser ou gestor do setor suporte)
    is_super_or_gestor = check_user_full_permission(request.user)

    # Renderiza o template de índice com os dados paginados e os filtros aplicados
    return render(request, 'form/index.html', {
        'page_obj': page_obj,
        'is_super_or_gestor': is_super_or_gestor,
        # Passa os parâmetros GET para manter o estado dos filtros no template
        'filtros': request.GET,
    })



def get_opcoes_filtro(request):
    """
    Retorna opções de filtro (países, marcas, modelos, anos) em formato JSON,
    baseado nos filtros de país e marca já aplicados.
    
    Útil para preencher dinamicamente dropdowns de filtro.
    """
    # Obtém os parâmetros de filtro da requisição
    pais_filtro = request.GET.get('pais', '')
    marca_filtro = request.GET.get('marca', '')
    
    # Inicia a consulta com todos os veículos
    consulta_filtrada = Veiculo.objects.all()
    
    # Aplica filtro de país, se fornecido
    if pais_filtro:
        consulta_filtrada = consulta_filtrada.filter(pais__icontains=pais_filtro)
    # Aplica filtro de marca, se fornecido
    if marca_filtro:
        consulta_filtrada = consulta_filtrada.filter(brand__icontains=marca_filtro)
    
    # Prepara os dados de resposta, obtendo valores distintos e ordenados
    opcoes_filtro = {
        'paises': list(consulta_filtrada.order_by('pais').values_list('pais', flat=True).distinct()),
        'marcas': list(consulta_filtrada.order_by('brand').values_list('brand', flat=True).distinct()),
        'modelos': list(consulta_filtrada.order_by('modelo').values_list('modelo', flat=True).distinct()),
        'anos': list(consulta_filtrada.order_by('ano').values_list('ano', flat=True).distinct()),
    }
    
    # Retorna as opções de filtro como resposta JSON
    return JsonResponse(opcoes_filtro)

def update_vehicle(request):
    """
    Atualiza um campo específico de um veículo via requisição POST.
    
    Esta função é uma alternativa mais simples para update_vehicle_field,
    mas é menos robusta em termos de tratamento de exibição de valores.
    """
    if request.method == 'POST':
        try:
            # Obtém o ID, nome do campo e novo valor da requisição POST
            veiculo_id = request.POST.get('id')
            nome_campo = request.POST.get('field')
            novo_valor = request.POST.get('value')
            
            # Busca o veículo pelo ID
            veiculo = Veiculo.objects.get(id=veiculo_id)
            
            # Atualiza o atributo do objeto e salva no banco de dados
            setattr(veiculo, nome_campo, novo_valor)
            veiculo.save()
            
            # Registra no log do admin
            if request.user.is_authenticated:
                LogEntry.objects.log_action(
                    user_id=request.user.id,
                    content_type_id=ContentType.objects.get_for_model(veiculo).pk,
                    object_id=veiculo.pk,
                    object_repr=str(veiculo),
                    action_flag=CHANGE,
                    change_message=json.dumps([{'changed': {'fields': [nome_campo]}}])
                )
            
            # Retorna sucesso com o novo valor
            return JsonResponse({
                'status': 'success',
                'new_display': novo_valor
            })
        except Veiculo.DoesNotExist:
            # Trata o caso de veículo não encontrado
            return JsonResponse({'status': 'error', 'message': 'Veículo não encontrado'}, status=404)
        except Exception as e:
            # Trata outros erros de atualização
            return JsonResponse({'status': 'error', 'message': f'Erro ao atualizar veículo: {str(e)}'}, status=400)
            
    # Retorna erro se o método não for POST
    return JsonResponse({'status': 'error', 'message': 'Método não permitido'}, status=405)

def update_vehicle_field(request):
    """
    Atualiza um campo específico de um veículo e retorna o valor de exibição (display value)
    para campos com choices definidos no modelo.
    
    É a função de atualização mais robusta.
    """
    if request.method == 'POST':
        # Obtém os dados da requisição POST
        veiculo_id = request.POST.get('id')
        nome_campo = request.POST.get('field')
        novo_valor = request.POST.get('value')
        
        try:
            # 1. Busca o veículo
            veiculo = Veiculo.objects.get(id=veiculo_id)
            
            # 2. Atualiza o campo e salva, especificando o campo para otimização
            setattr(veiculo, nome_campo, novo_valor)
            veiculo.save(update_fields=[nome_campo])

            # Registra no log do admin
            if request.user.is_authenticated:
                LogEntry.objects.log_action(
                    user_id=request.user.id,
                    content_type_id=ContentType.objects.get_for_model(veiculo).pk,
                    object_id=veiculo.pk,
                    object_repr=str(veiculo),
                    action_flag=CHANGE,
                    change_message=json.dumps([{'changed': {'fields': [nome_campo]}}])
                )

            # 3. Prepara os dados de resposta
            # Tenta obter o valor de exibição (display value) se o campo tiver choices
            display_func = getattr(veiculo, f'get_{nome_campo}_display', lambda: novo_valor)
            display_value = display_func()

            response_data = {
                'status': 'success',
                'new_value': novo_valor,
                'display_value': display_value
            }

            # 4. Retorna a resposta JSON
            return JsonResponse(response_data)
        
        except Veiculo.DoesNotExist:
            # Trata o caso de veículo não encontrado
            return JsonResponse({'status': 'error', 'message': 'Veículo não encontrado'}, status=404)
        except Exception as e:
            # Trata outros erros de atualização
            return JsonResponse({'status': 'error', 'message': f'Erro ao atualizar campo: {str(e)}'}, status=400)
        
    # Retorna erro se o método não for POST
    return JsonResponse({'status': 'error', 'message': 'Método não permitido'}, status=405)

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("form")
def dashboard_edicoes(request):
    """
    Dashboard para superusuários e gestores visualizarem as últimas edições.
    """
    # Verifica se o usuário tem permissão total (superuser ou gestor do setor suporte)
    if not check_user_full_permission(request.user):
        return redirect('index_form')

    # Filtros de data
    filtro_data = request.GET.get('filtro_selected', 'hoje')
    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')

    # Pega os logs da aplicação 'form' e otimiza a consulta
    logs = LogEntry.objects.filter(content_type__app_label='form').select_related('user', 'content_type').order_by('-action_time')
    
    hoje = timezone.localtime()
    inicio_dia = hoje.replace(hour=0, minute=0, second=0, microsecond=0)

    if filtro_data == 'hoje':
        logs = logs.filter(action_time__gte=inicio_dia)
    elif filtro_data == 'ontem':
        inicio_ontem = inicio_dia - timedelta(days=1)
        logs = logs.filter(action_time__range=(inicio_ontem, inicio_dia))
    elif filtro_data == 'semanal':
        logs = logs.filter(action_time__gte=inicio_dia - timedelta(days=7))
    elif filtro_data == 'mensal':
        logs = logs.filter(action_time__gte=inicio_dia - timedelta(days=30))
    elif filtro_data == 'anual':
        logs = logs.filter(action_time__gte=inicio_dia - timedelta(days=365))
    elif filtro_data == 'personalizada' and data_inicio and data_fim:
        try:
            # Para data personalizada, garantimos que cubra o dia inteiro da data_fim
            inicio_p = timezone.make_aware(datetime.strptime(data_inicio, '%Y-%m-%d'))
            fim_p = timezone.make_aware(datetime.strptime(data_fim, '%Y-%m-%d')) + timedelta(days=1)
            logs = logs.filter(action_time__range=(inicio_p, fim_p))
        except:
            pass

    # Total de alterações (logs individuais filtrados)
    total_alteracoes = logs.count()

    # Agrupamento para evitar repetições do mesmo registro no mesmo dia
    eventos_agrupados = {}

    for log in logs:
        # Chave de agrupamento: (tipo_do_objeto, id_do_objeto, data)
        key = (log.content_type_id, log.object_id, log.action_time.date())
        
        # Tentar extrair campos alterados da mensagem JSON
        campos_atuais = []
        if log.change_message:
            try:
                msg_json = json.loads(log.change_message)
                if isinstance(msg_json, list) and len(msg_json) > 0:
                    changed = msg_json[0].get('changed', {})
                    if 'fields' in changed:
                        campos_atuais = changed['fields']
                    elif 'added' in msg_json[0]:
                        campos_atuais = ['(Novo Registro)']
            except:
                pass

        if key not in eventos_agrupados:
            acao = ""
            if log.action_flag == ADDITION:
                acao = "Adicionou"
            elif log.action_flag == CHANGE:
                acao = "Editou"
            elif log.action_flag == DELETION:
                acao = "Deletou"
            
            try:
                modelo_nome = log.content_type.model_class()._meta.verbose_name.title()
            except:
                modelo_nome = str(log.content_type.model).title()

            eventos_agrupados[key] = {
                'usuario': log.user.get_full_name() or log.user.username,
                'acao': acao,
                'objeto': log.object_repr,
                'modelo': modelo_nome,
                'campos': set(campos_atuais),
                'data_hora': log.action_time,
                'count': 1,
                'object_id': log.object_id,
                'content_type_id': log.content_type_id
            }
        else:
            # Se já existe, acumula os campos e incrementa o contador
            eventos_agrupados[key]['campos'].update(campos_atuais)
            eventos_agrupados[key]['count'] += 1
            
            # Mantém a data/hora mais recente do agrupamento
            if log.action_time > eventos_agrupados[key]['data_hora']:
                eventos_agrupados[key]['data_hora'] = log.action_time

    # Converte para lista e ordena por data/hora decrescente
    eventos = sorted(eventos_agrupados.values(), key=lambda x: x['data_hora'], reverse=True)

    # --- PAGINAÇÃO ---
    per_page = request.GET.get('per_page', '10')
    if per_page == 'todos':
        page_obj = eventos
    else:
        try:
            per_page_int = int(per_page)
        except:
            per_page_int = 10
            
        paginator = Paginator(eventos, per_page_int)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

    # Converte os sets de campos para strings formatadas e busca valores atuais
    # Nota: se page_obj for Paginator, iteramos sobre page_obj.object_list
    iter_obj = page_obj.object_list if not per_page == 'todos' else page_obj
    
    for ev in iter_obj:
        if ev['campos']:
            ev['campos_display'] = ", ".join(sorted(list(ev['campos'])))
            
            # Busca valores atuais para o popup
            ev['detalhes_valores'] = []
            try:
                ct = ContentType.objects.get_for_id(ev['content_type_id'])
                model_class = ct.model_class()
                obj = model_class.objects.get(pk=ev['object_id'])
                
                for field_name in sorted(list(ev['campos'])):
                    if field_name == '(Novo Registro)': continue
                    try:
                        # Tenta pegar valor de exibição ou valor bruto
                        display_func = getattr(obj, f'get_{field_name}_display', None)
                        if display_func:
                            val = str(display_func())
                        else:
                            val = str(getattr(obj, field_name))
                        
                        field_label = model_class._meta.get_field(field_name).verbose_name
                        ev['detalhes_valores'].append({
                            'label': field_label,
                            'valor': val
                        })
                    except:
                        pass
            except:
                # Se o objeto foi deletado, não conseguimos buscar os valores atuais
                pass
        else:
            ev['campos_display'] = ""

    return render(request, 'form/dashboard.html', {
        'page_obj': page_obj,
        'filtro_selected': filtro_data,
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'total_alteracoes': total_alteracoes,
        'per_page': per_page,
    })
