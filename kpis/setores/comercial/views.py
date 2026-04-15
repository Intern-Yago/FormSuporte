import csv
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from . import services

@login_required
def dashboard(request):
    """Renderiza a página principal do dashboard comercial com metadados de filtros."""
    data = services.get_dashboard_data()
    filters_data = data.get('filters', {}) if data else {}
    
    context = {
        'filters': filters_data,
        'filters_meta': {
            'vendedores': 'Vendedor',
            'produtos': 'Produto',
            'estados': 'Estado',
            'regioes': 'Região',
        }
    }
    return render(request, 'kpis/comercial/dashboard.html', context)

@login_required
def api_dashboard_data(request):
    """Endpoint que retorna os dados filtrados em JSON."""
    filters = {
        'vendedores': request.GET.getlist('vendedores[]'),
        'produtos': request.GET.getlist('produtos[]'),
        'estados': request.GET.getlist('estados[]'),
        'regioes': request.GET.getlist('regioes[]'),
        'anoMesInicio': request.GET.get('anoMesInicio'),
        'anoMesFim': request.GET.get('anoMesFim'),
    }
    filters = {k: v for k, v in filters.items() if v}

    data = services.get_dashboard_data()
    if not data:
        return JsonResponse({'error': 'Erro ao carregar dados'}, status=500)

    raw_records = data.get('raw_records', [])
    filtered_records = services.apply_filters(raw_records, filters)

    return JsonResponse({
        'summary': services.get_summary(filtered_records),
        'sales_by_state': services.aggregate_by_state(filtered_records),
        'sales_by_region': services.aggregate_by_region(filtered_records),
        'sales_by_seller': services.aggregate_by_seller(filtered_records),
        'sales_by_product': services.aggregate_by_product(filtered_records),
        'sales_over_time': services.aggregate_over_time(filtered_records),
    })

@login_required
def export_csv(request):
    scope = request.GET.get('scope', 'all')
    filters = {
        'vendedores': request.GET.getlist('vendedores[]'),
        'produtos': request.GET.getlist('produtos[]'),
        'estados': request.GET.getlist('estados[]'),
        'regioes': request.GET.getlist('regioes[]'),
        'anoMesInicio': request.GET.get('anoMesInicio'),
        'anoMesFim': request.GET.get('anoMesFim'),
    }
    filters = {k: v for k, v in filters.items() if v}
    data = services.get_dashboard_data()
    if not data: return HttpResponse(status=404)
    records = services.apply_filters(data.get('raw_records', []), filters)
    
    response = HttpResponse(content_type='text/csv')
    if scope == 'sellers':
        response['Content-Disposition'] = 'attachment; filename="vendedores.csv"'
        writer = csv.writer(response)
        writer.writerow(['Vendedor', 'Valor', 'Qtd', 'Vendas'])
        for s in services.aggregate_by_seller(records):
            writer.writerow([s['vendedor'], s['valor'], s['quantidade'], s['num_vendas']])
    elif scope == 'products':
        response['Content-Disposition'] = 'attachment; filename="produtos.csv"'
        writer = csv.writer(response)
        writer.writerow(['Produto', 'Valor', 'Qtd', 'Vendas'])
        for p in services.aggregate_by_product(records):
            writer.writerow([p['produto'], p['valor'], p['quantidade'], p['num_vendas']])
    else:
        response['Content-Disposition'] = 'attachment; filename="detalhado.csv"'
        writer = csv.writer(response)
        writer.writerow(['Data', 'Vendedor', 'Produto', 'Qtd', 'Valor', 'Cliente'])
        for r in records:
            writer.writerow([r.get('data'), r.get('vendedor'), r.get('produto'), r.get('quantidade'), r.get('valor'), r.get('cliente')])
    return response
