import requests
from django.core.cache import cache
from collections import defaultdict

DATA_URL = "https://d2xsxph8kpxj0f.cloudfront.net/310419663031502925/D4P3CrCsrm9CkcauQFtqUW/dashboard_data_4129046b.json"
CACHE_KEY = "comercial_dashboard_data"
CACHE_TTL = 3600

def get_dashboard_data():
    data = cache.get(CACHE_KEY)
    if not data:
        try:
            resp = requests.get(DATA_URL, timeout=30)
            if resp.status_code == 200:
                # Forçar decodificação correta para tratar acentos (UTF-8)
                resp.encoding = 'utf-8'
                data = resp.json()
                cache.set(CACHE_KEY, data, CACHE_TTL)
        except Exception: return None
    return data

def apply_filters(records, filters):
    filtered = records
    
    if filters.get('vendedores'):
        s = set(filters['vendedores'])
        filtered = [r for r in filtered if r.get('vendedor') in s]
    if filters.get('produtos'):
        s = set(filters['produtos'])
        filtered = [r for r in filtered if r.get('produto') in s]
    if filters.get('estados'):
        s = set(filters['estados'])
        filtered = [r for r in filtered if r.get('estado') in s]
    if filters.get('regioes'):
        s = set(filters['regioes'])
        filtered = [r for r in filtered if r.get('regiao') in s]
        
    # Filtro de período compatível com formato "YYYY-MM"
    if filters.get('anoMesInicio'):
        start = filters['anoMesInicio'] # Formato esperado: "YYYY-MM"
        filtered = [r for r in filtered if (r.get('ano_mes') or "") >= start]
    if filters.get('anoMesFim'):
        end = filters['anoMesFim'] # Formato esperado: "YYYY-MM"
        filtered = [r for r in filtered if (r.get('ano_mes') or "") <= end]
        
    return filtered

def get_summary(records):
    total_v = sum(r.get('valor', 0) for r in records)
    total_q = sum(r.get('quantidade', 0) for r in records)
    vends = {r.get('vendedor') for r in records if r.get('vendedor')}
    ests = {r.get('estado') for r in records if r.get('estado')}
    prods = {r.get('produto') for r in records if r.get('produto')}
    clis = {r.get('cliente') for r in records if r.get('cliente')}
    return {
        'total_valor': round(total_v, 2),
        'total_quantidade': total_q,
        'total_registros': len(records),
        'total_vendedores': len(vends),
        'total_estados': len(ests),
        'total_produtos': len(prods),
        'total_clientes_unicos': len(clis),
    }

def aggregate_by_state(records):
    res = {}
    for r in records:
        k = r.get('estado')
        if not k: continue
        if k not in res: res[k] = {'estado': k, 'sigla': r.get('sigla'), 'valor': 0, 'quantidade': 0}
        res[k]['valor'] += r.get('valor', 0)
        res[k]['quantidade'] += r.get('quantidade', 0)
    return sorted(res.values(), key=lambda x: x['valor'], reverse=True)

def aggregate_by_region(records):
    res = {}
    for r in records:
        k = r.get('regiao')
        if not k: continue
        if k not in res: res[k] = {'regiao': k, 'valor': 0, 'quantidade': 0}
        res[k]['valor'] += r.get('valor', 0)
        res[k]['quantidade'] += r.get('quantidade', 0)
    return sorted(res.values(), key=lambda x: x['valor'], reverse=True)

def aggregate_by_seller(records):
    res = {}
    for r in records:
        k = r.get('vendedor')
        if not k: continue
        if k not in res: res[k] = {'vendedor': k, 'valor': 0, 'quantidade': 0, 'num_vendas': 0, 'prods': defaultdict(int)}
        res[k]['valor'] += r.get('valor', 0)
        res[k]['quantidade'] += r.get('quantidade', 0)
        res[k]['num_vendas'] += 1
        res[k]['prods'][r.get('produto')] += r.get('quantidade', 0)
    
    out = []
    for s in res.values():
        top = sorted(s['prods'].items(), key=lambda x: x[1], reverse=True)[:2]
        out.append({
            'vendedor': s['vendedor'], 'valor': round(s['valor'], 2), 
            'quantidade': s['quantidade'], 'num_vendas': s['num_vendas'],
            'top_produtos': [p[0] for p in top]
        })
    return sorted(out, key=lambda x: x['valor'], reverse=True)

def aggregate_by_product(records):
    res = {}
    for r in records:
        k = r.get('produto')
        if not k: continue
        if k not in res: res[k] = {'produto': k, 'valor': 0, 'quantidade': 0, 'num_vendas': 0}
        res[k]['valor'] += r.get('valor', 0)
        res[k]['quantidade'] += r.get('quantidade', 0)
        res[k]['num_vendas'] += 1
    for p in res.values(): p['valor'] = round(p['valor'], 2)
    return sorted(res.values(), key=lambda x: x['valor'], reverse=True)

def aggregate_over_time(records):
    res = {}
    for r in records:
        k = r.get('ano_mes')
        if not k: continue
        if k not in res: res[k] = {'periodo': k, 'valor': 0, 'quantidade': 0, 'num_vendas': 0}
        res[k]['valor'] += r.get('valor', 0)
        res[k]['quantidade'] += r.get('quantidade', 0)
        res[k]['num_vendas'] += 1
    return sorted([{'periodo': k, 'valor': round(v['valor'], 2), 'quantidade': v['quantidade'], 'num_vendas': v['num_vendas']} for k,v in res.items()], key=lambda x: x['periodo'])
