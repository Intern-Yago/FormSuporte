# views.py - Lógica de Views e API para o App 'API'

import os
import sys
from datetime import datetime

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from simulador.models import Registro
from .models import Equipamentos, TipoEquipamento, MarcaEquipamento
from .serializers import (
    EquipamentosSerializer, TipoEquipamentoSerializer, MarcaEquipamentoSerializer, 
    ClienteUnificadoSerializer, ClienteSuporteSerializer
)
from situacao_veiculo.models import Cliente as ClienteSuporte
from clientes.models import Cliente as ClienteUnificado
from rest_framework import status as http_status

from django.db.models import Q

import re
import unicodedata
from urllib.parse import quote
from django.shortcuts import get_object_or_404



def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def sanitize_filename_component(value: str, max_len: int = 80) -> str:
    if not value:
        return ""

    s = str(value).strip()
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    s = re.sub(r"\s+", "_", s)
    s = s.strip("._ ")

    if len(s) > max_len:
        s = s[:max_len].rstrip("._ ")

    return s


def ascii_fallback(value: str) -> str:
    if not value:
        return ""
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(c for c in nfkd if ord(c) < 128)


if sys.platform == 'win32':
    try:
        gtk_paths = [
            r'C:\Program Files\GTK3-Runtime Win64\bin',
            r'C:\Program Files (x86)\GTK3-Runtime Win64\bin',
            r'C:\gtk\bin',
        ]

        for path in gtk_paths:
            if os.path.exists(path):
                os.add_dll_directory(path)
                os.environ['PATH'] = path + os.pathsep + os.environ['PATH']
                break
    except Exception as e:
        print(f"Erro na configuração do GTK (Windows): {e}")
elif sys.platform.startswith('linux'):
    print("✅ Ambiente Linux detectado - WeasyPrint funcionará nativamente (se dependências instaladas)")


try:
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


class EquipamentosViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Equipamentos.objects.all().order_by('nome')
    serializer_class = EquipamentosSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]


class TipoEquipamentoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TipoEquipamento.objects.all().order_by('nome')
    serializer_class = TipoEquipamentoSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]


class MarcaEquipamentoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MarcaEquipamento.objects.all().order_by('nome')
    serializer_class = MarcaEquipamentoSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]


class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ClienteUnificado.objects.all().order_by('nome')
    serializer_class = ClienteUnificadoSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]


@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def cliente_by_doc(request, cpf_cnpj=None):
    try:
        # Tenta pegar da URL (path) ou da QueryString (?cpf_cnpj=...)
        doc_raw = cpf_cnpj or request.GET.get('cpf_cnpj') or ''
        doc_in = _digits_only(doc_raw)
        
        if not doc_in:
            return Response({'ok': False, 'message': 'Informe o CPF ou CNPJ.'}, status=http_status.HTTP_400_BAD_REQUEST)

        # Busca no modelo unificado de clientes
        cliente = (
            ClienteUnificado.objects
            .filter(Q(cpf=doc_in) | Q(cnpj=doc_in))
            .order_by('-id')
            .first()
        )

        if not cliente:
            return Response({'ok': False, 'message': 'Cliente não encontrado.'}, status=http_status.HTTP_404_NOT_FOUND)

        serializer = ClienteUnificadoSerializer(cliente)
        return Response({
            'ok': True,
            'data': serializer.data
        }, status=http_status.HTTP_200_OK)
    except Exception as e:
        print(f"[ERROR 500 - API]: {e}")
        import traceback
        traceback.print_exc()
        return Response({'ok': False, 'error': str(e)}, status=500)


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def cliente_search(request):
    serial_in = (request.data.get('serial') or '').strip()
    if not serial_in:
        return Response({'ok': False, 'message': 'Informe o serial.'}, status=http_status.HTTP_400_BAD_REQUEST)

    cliente = (
        ClienteSuporte.objects
        .filter(Q(serial__iexact=serial_in) | Q(serial_sec__iexact=serial_in))
        .order_by('-id')
        .first()
    )

    if not cliente:
        return Response({'ok': False, 'message': 'Serial não encontrado.'}, status=http_status.HTTP_404_NOT_FOUND)

    serializer = ClienteSuporteSerializer(cliente)
    matched_by = 'serial_sec' if (cliente.serial_sec or '').casefold() == serial_in.casefold() else 'serial'

    return Response({
        'ok': True,
        'data': serializer.data,
        'meta': {
            'searched_serial': serial_in,
            'matched_by': matched_by,
            'principal_serial': cliente.serial,
        }
    }, status=http_status.HTTP_200_OK)


@csrf_exempt
def format_currency(value):
    try:
        valor_float = float(value)
        formato_eua = f"R$ {valor_float:,.2f}"
        temp_troca = formato_eua.replace(',', 'X')
        decimal_br = temp_troca.replace('.', ',')
        final_br = decimal_br.replace('X', '.')
        return final_br
    except (ValueError, TypeError):
        return "R$ 0,00"


@csrf_exempt
def html_to_pdf_weasyprint(html_string):
    if not WEASYPRINT_AVAILABLE:
        print("WeasyPrint não está disponível. Não é possível gerar PDF.")
        return None

    try:
        font_config = FontConfiguration()
        base_url = str(settings.BASE_DIR) if settings.DEBUG else settings.STATIC_URL
        html = HTML(string=html_string, base_url=base_url)
        pdf_data = html.write_pdf(font_config=font_config)
        return pdf_data
    except Exception as e:
        print(f"Erro ao gerar PDF com WeasyPrint: {e}")
        return None


@api_view(['POST'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def generate_pdf(request):
    """
    Endpoint da API para gerar PDF e salvar snapshot financeiro completo no Registro.
    """
    try:
        data = request.data

        usar_precos_cliente = bool(data.get("usarPrecosCliente"))
        itens_pdf = data.get("itensPDF") or []
        equipamento_ids = data.get("equipamentos", [])
        quantidades = data.get("quantidades", [])

        equipamentos_data = []

        # ✅ ESTE É O VALOR À VISTA CORRETO:
        # soma do avista/base dos equipamentos
        valor_avista_total = 0.0

        if usar_precos_cliente and isinstance(itens_pdf, list) and len(itens_pdf) > 0:
            for item in itens_pdf:
                try:
                    nome = item.get("nome") or "Equipamento"
                    qtd = int(item.get("quantidade") or 1)

                    # valores COM taxa
                    valor_total = float(item.get("valorTotal") or 0)
                    valor_unit = float(item.get("valorUnitario") or (valor_total / qtd if qtd else 0))

                    # valores À VISTA / SEM TAXA
                    valor_base_total = float(item.get("valorBaseTotal") or 0)
                    valor_base_unit = float(item.get("valorBaseUnitario") or (valor_base_total / qtd if qtd else 0))

                    # ✅ soma SOMENTE o avista dos equipamentos
                    valor_avista_total += valor_base_total

                    equipamentos_data.append({
                        "nome": nome,
                        "quantidade": qtd,

                        "valor_unitario": valor_unit,
                        "valor_unitario_formatado": format_currency(valor_unit),
                        "valor_total": valor_total,
                        "valor_total_formatado": format_currency(valor_total),

                        "valor_avista_unitario": valor_base_unit,
                        "valor_avista_unitario_formatado": format_currency(valor_base_unit),
                        "valor_avista_total": valor_base_total,
                        "valor_avista_total_formatado": format_currency(valor_base_total),
                    })
                except Exception:
                    continue
        else:
            # fallback antigo: se não vier itens do cliente, o sistema não tem separação
            # entre taxado e à vista, então usa o mesmo valor
            for i, equipamento_id in enumerate(equipamento_ids):
                try:
                    try:
                        quantidade = int(quantidades[i])
                    except (ValueError, TypeError, IndexError):
                        quantidade = 1

                    equipamento = Equipamentos.objects.get(id=equipamento_id)

                    localizacao = data.get("localizacao")
                    faturamento = data.get("faturamento")

                    if localizacao == "SP":
                        valor_unitario = float(equipamento.custo_geral)
                    elif faturamento == "CPF":
                        valor_unitario = float(equipamento.custo_cpf)
                    else:
                        valor_unitario = float(equipamento.custo_cnpj)

                    valor_total_item = valor_unitario * quantidade

                    valor_avista_total += valor_total_item

                    equipamentos_data.append({
                        "nome": equipamento.nome,
                        "quantidade": quantidade,

                        "valor_unitario": valor_unitario,
                        "valor_unitario_formatado": format_currency(valor_unitario),
                        "valor_total": valor_total_item,
                        "valor_total_formatado": format_currency(valor_total_item),

                        "valor_avista_unitario": valor_unitario,
                        "valor_avista_unitario_formatado": format_currency(valor_unitario),
                        "valor_avista_total": valor_total_item,
                        "valor_avista_total_formatado": format_currency(valor_total_item),
                    })
                except Exception:
                    continue

        subtotal_exib = data.get("subtotalEquipamentosExibicao", None)
        try:
            subtotal_exib = float(subtotal_exib) if subtotal_exib is not None else None
        except Exception:
            subtotal_exib = None

        valor_total_equipamentos = subtotal_exib if subtotal_exib is not None else sum(
            item["valor_total"] for item in equipamentos_data
        )

        desconto_valor = float(data.get('desconto', 0) or 0)
        entrada_valor = float(data.get('entrada', 0) or 0)
        frete_valor = float(data.get('frete', 0) or 0)
        tipo_pagamento = (data.get('tipoPagamento') or '').strip()
        tem_frete = frete_valor > 0

        valor_total_equipamentos_exib = valor_total_equipamentos
        valor_total_final = float(data.get("valorTotal") or valor_total_equipamentos)

        if tipo_pagamento == 'Cartao':
            valor_total_equipamentos_exib = max(0.0, valor_total_final - entrada_valor)

        parcelas_qtd = int(data.get('parcelas', 0) or 0)
        parcela_base = float(data.get('valorParcela', 0) or 0)
        ultima_parcela = parcela_base
        parcelas_texto_extra = None

        if parcelas_qtd > 0:
            total_cent = round(valor_total_final * 100)
            entrada_cent = round(entrada_valor * 100)
            saldo_cent = max(0, total_cent - entrada_cent)
            parcela_base_cent = saldo_cent // parcelas_qtd
            resto_cent = saldo_cent - (parcela_base_cent * parcelas_qtd)
            ultima_parcela_cent = parcela_base_cent + resto_cent

            parcela_base = parcela_base_cent / 100.0
            ultima_parcela = ultima_parcela_cent / 100.0

        template_data = {
            'equipamentos': equipamentos_data,

            'entrada': entrada_valor,
            'entrada_formatado': format_currency(entrada_valor),

            'parcelas': parcelas_qtd,
            'localizacao': data.get('localizacao', ''),
            'faturamento': data.get('faturamento', ''),

            'valorParcela': parcela_base,
            'valorParcela_formatado': format_currency(parcela_base),
            'ultimaParcela': ultima_parcela,
            'ultimaParcela_formatado': format_currency(ultima_parcela),
            'parcelasTextoExtra': parcelas_texto_extra,

            'valorTotal': valor_total_equipamentos_exib,
            'valorTotal_formatado': format_currency(valor_total_equipamentos_exib),

            'valorTotalFinal': valor_total_final,
            'valorTotalFinal_formatado': format_currency(valor_total_final),

            'desconto': desconto_valor,
            'desconto_formatado': format_currency(desconto_valor),

            'observacao': data.get('observacao', ''),
            'descricao': data.get('descricao', ''),
            'tipoPagamento': data.get('tipoPagamento', ''),
            'nomeVendedor': data.get('nomeVendedor', ''),
            'nomeCNPJ': data.get('nomeCNPJ', ''),
            'nomeCliente': data.get('nomeCliente', ''),

            'subtotalEquipamentos': valor_total_equipamentos,
            'subtotalEquipamentos_formatado': format_currency(valor_total_equipamentos_exib),

            # ✅ AGORA O PDF USA O À VISTA CORRETO
            'valorFinalSemTaxa': valor_avista_total,
            'valorFinalSemTaxa_formatado': format_currency(valor_avista_total),
        }

        if tem_frete:
            template_data['frete'] = frete_valor
            template_data['frete_formatado'] = format_currency(frete_valor)

        hoje = datetime.now()
        if hoje.month == 12:
            validade = datetime(hoje.year + 1, 1, 1)
        else:
            validade = datetime(hoje.year, hoje.month + 1, 1)

        template_data['validadeRelatorio'] = validade.strftime('%d/%m/%Y')
        template_data['dataGeracao'] = hoje.strftime('%d/%m/%Y')
        template_data['horaGeracao'] = hoje.strftime('%H:%M')

        try:
            nomeVendedor = (data.get('nomeVendedor') or '').strip()

            tipo_documento = (data.get('faturamento') or '').strip().upper()
            if tipo_documento not in ('CPF', 'CNPJ'):
                tipo_documento = 'CPF'

            documento = (data.get('nomeCNPJ') or '').strip()
            if not documento:
                documento = (data.get('cpfCnpj') or data.get('documento') or '').strip()

            forma_pagamento_raw = (data.get('tipoPagamento') or '').strip()
            mapa_pagamento = {
                'cartao': 'Cartao',
                'cartão': 'Cartao',
                'credito': 'Cartao',
                'crédito': 'Cartao',
                'boleto': 'Boleto',
                'pix': 'Pix',
            }
            forma_pagamento = mapa_pagamento.get(forma_pagamento_raw.lower(), forma_pagamento_raw)
            if forma_pagamento not in ('Cartao', 'Boleto', 'Pix'):
                forma_pagamento = 'Cartao'

            equipamentos_resumo = ", ".join(
                f"{item.get('nome', 'Equipamento')} ({int(item.get('quantidade') or 1)}x)"
                for item in (equipamentos_data or [])
            )

            Registro.objects.create(
                nome_vendedor=nomeVendedor,
                nome_cliente=(data.get('nomeCliente') or '').strip(),
                tipo_documento=tipo_documento,
                documento=documento,
                forma_pagamento=forma_pagamento,

                equipamentos_resumo=equipamentos_resumo,
                equipamentos_json=equipamentos_data,

                valor_entrada=entrada_valor or 0,
                quantidade_parcelas=parcelas_qtd if parcelas_qtd > 0 else 1,
                valor_desconto=desconto_valor or 0,
                valor_frete=frete_valor if tem_frete else 0,

                # ✅ SALVA O À VISTA CERTO
                valor_avista=valor_avista_total or 0,

                observacoes=(data.get('observacao') or '').strip(),
                localizacao=data.get('localizacao', ''),
            )
        except Exception as e:
            print(f"Erro ao salvar Registro: {e}")

        html_string = render_to_string('api/pdf_simulador.html', template_data)
        pdf = html_to_pdf_weasyprint(html_string)

        if pdf:
            response = HttpResponse(pdf, content_type='application/pdf')
            raw_nome = data.get('nomeCliente') or ""
            safe_nome = sanitize_filename_component(raw_nome)
            suffix = safe_nome or hoje.strftime('%Y-%m-%d_%H-%M')
            filename = f"Simulação_de_Venda_{suffix}.pdf"
            filename_ascii = ascii_fallback(filename) or f"Simulacao_de_Venda_{hoje.strftime('%Y-%m-%d_%H-%M')}.pdf"
            quoted = quote(filename)
            response['Content-Disposition'] = (
                f'attachment; filename="{filename_ascii}"; filename*=UTF-8\'\'{quoted}'
            )
            return response

        response = HttpResponse(html_string, content_type='text/html')
        filename = f"Simulação_HTML_{hoje.strftime('%Y-%m-%d_%H-%M')}.html"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    except Exception as e:
        print(f"Erro na geração do PDF: {e}")
        return Response({'error': str(e)}, status=500)

@csrf_exempt
def html_to_pdf(html_string):
    return html_to_pdf_weasyprint(html_string)

@api_view(['PUT'])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def update_registro(request, pk):
    """
    Atualiza Registro mantendo snapshot correto do valor à vista.
    """
    try:
        registro = Registro.objects.get(pk=pk)
        data = request.data

        usar_precos_cliente = bool(data.get("usarPrecosCliente"))
        itens_pdf = data.get("itensPDF") or []
        equipamentos_data = []
        valor_avista = 0.0

        if usar_precos_cliente and isinstance(itens_pdf, list) and len(itens_pdf) > 0:
            for item in itens_pdf:
                try:
                    nome = item.get("nome") or "Equipamento"
                    qtd = int(item.get("quantidade") or 1)

                    valor_total = float(item.get("valorTotal") or 0)
                    valor_unit = float(item.get("valorUnitario") or (valor_total / qtd if qtd else 0))

                    valor_base_total = float(item.get("valorBaseTotal") or 0)
                    valor_base_unit = float(item.get("valorBaseUnitario") or (valor_base_total / qtd if qtd else 0))

                    # ✅ soma só o à vista
                    valor_avista += valor_base_total

                    equipamentos_data.append({
                        "nome": nome,
                        "quantidade": qtd,

                        "valor_unitario": valor_unit,
                        "valor_unitario_formatado": format_currency(valor_unit),
                        "valor_total": valor_total,
                        "valor_total_formatado": format_currency(valor_total),

                        "valor_avista_unitario": valor_base_unit,
                        "valor_avista_unitario_formatado": format_currency(valor_base_unit),
                        "valor_avista_total": valor_base_total,
                        "valor_avista_total_formatado": format_currency(valor_base_total),
                    })
                except Exception:
                    continue
        else:
            equipamento_ids = data.get("equipamentos", [])
            quantidades = data.get("quantidades", [])

            for i, equipamento_id in enumerate(equipamento_ids):
                try:
                    try:
                        quantidade = int(quantidades[i])
                    except (ValueError, TypeError, IndexError):
                        quantidade = 1

                    equipamento = Equipamentos.objects.get(id=equipamento_id)

                    localizacao = data.get("localizacao")
                    faturamento = data.get("faturamento")

                    if localizacao == "SP":
                        valor_unitario = float(equipamento.custo_geral)
                    elif faturamento == "CPF":
                        valor_unitario = float(equipamento.custo_cpf)
                    else:
                        valor_unitario = float(equipamento.custo_cnpj)

                    valor_total_item = valor_unitario * quantidade
                    valor_avista += valor_total_item

                    equipamentos_data.append({
                        "nome": equipamento.nome,
                        "quantidade": quantidade,

                        "valor_unitario": valor_unitario,
                        "valor_unitario_formatado": format_currency(valor_unitario),
                        "valor_total": valor_total_item,
                        "valor_total_formatado": format_currency(valor_total_item),

                        "valor_avista_unitario": valor_unitario,
                        "valor_avista_unitario_formatado": format_currency(valor_unitario),
                        "valor_avista_total": valor_total_item,
                        "valor_avista_total_formatado": format_currency(valor_total_item),
                    })
                except Exception:
                    continue

        entrada_valor = float(data.get('entrada', 0) or 0)
        desconto_valor = float(data.get('desconto', 0) or 0)
        frete_valor = float(data.get('frete', 0) or 0)
        tem_frete = frete_valor > 0
        parcelas_qtd = int(data.get('parcelas', 0) or 0)

        tipo_documento = (data.get('faturamento') or '').strip().upper()
        if tipo_documento not in ('CPF', 'CNPJ'):
            tipo_documento = 'CPF'

        documento = (data.get('nomeCNPJ') or data.get('cpfCnpj') or data.get('documento') or '').strip()

        forma_pagamento_raw = (data.get('tipoPagamento') or '').strip()
        mapa_pagamento = {
            'cartao': 'Cartao',
            'cartão': 'Cartao',
            'credito': 'Cartao',
            'crédito': 'Cartao',
            'boleto': 'Boleto',
            'pix': 'Pix',
        }
        forma_pagamento = mapa_pagamento.get(forma_pagamento_raw.lower(), forma_pagamento_raw)
        if forma_pagamento not in ('Cartao', 'Boleto', 'Pix'):
            forma_pagamento = 'Cartao'

        equipamentos_resumo = ", ".join(
            f"{item.get('nome', 'Equipamento')} ({int(item.get('quantidade') or 1)}x)"
            for item in (equipamentos_data or [])
        )

        registro.nome_vendedor = (data.get('nomeVendedor') or '').strip()
        registro.nome_cliente = (data.get('nomeCliente') or '').strip()
        registro.tipo_documento = tipo_documento
        registro.documento = documento
        registro.forma_pagamento = forma_pagamento
        registro.localizacao = data.get('localizacao', '')

        if equipamentos_data:
            registro.equipamentos_resumo = equipamentos_resumo
            registro.equipamentos_json = equipamentos_data

        registro.valor_entrada = entrada_valor
        registro.quantidade_parcelas = parcelas_qtd if parcelas_qtd > 0 else 1
        registro.valor_desconto = desconto_valor
        registro.valor_frete = frete_valor if tem_frete else 0

        # ✅ SALVA O À VISTA CERTO
        registro.valor_avista = valor_avista

        registro.observacoes = (data.get('observacao') or '').strip()

        registro.save()

        return Response({'ok': True, 'message': 'Alterações salvas com sucesso!'}, status=http_status.HTTP_200_OK)

    except Registro.DoesNotExist:
        return Response({'ok': False, 'message': 'Registro não encontrado.'}, status=http_status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(f"Erro ao salvar alterações no Registro: {e}")
        return Response({'ok': False, 'error': str(e)}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['GET'])
@authentication_classes([TokenAuthentication, SessionAuthentication]) # 👇 Adicionamos a Sessão aqui!
@permission_classes([IsAuthenticated])
def baixar_pdf_registro(request, pk):
    """
    Gera o PDF de um Registro (Orçamento) JÁ EXISTENTE, 
    sem duplicar no banco de dados.
    """
    registro = get_object_or_404(Registro, pk=pk)

    equipamentos_data = registro.equipamentos_json or []
    valor_total_equipamentos = sum(float(item.get("valor_total", 0)) for item in equipamentos_data)

    # Refaz a matemática baseada nos dados salvos
    valor_total_final = valor_total_equipamentos - float(registro.valor_desconto) + float(registro.valor_frete)
    saldo = max(0, valor_total_final - float(registro.valor_entrada))
    parcelas_qtd = registro.quantidade_parcelas
    parcela_base = saldo / parcelas_qtd if parcelas_qtd > 0 else 0

    hoje = registro.criado_em
    validade = datetime(hoje.year + 1, 1, 1) if hoje.month == 12 else datetime(hoje.year, hoje.month + 1, 1)

    template_data = {
        'equipamentos': equipamentos_data,
        'entrada': float(registro.valor_entrada),
        'entrada_formatado': format_currency(registro.valor_entrada),
        'parcelas': parcelas_qtd,
        'localizacao': registro.localizacao,
        'faturamento': registro.tipo_documento,
        'valorParcela': parcela_base,
        'valorParcela_formatado': format_currency(parcela_base),
        'ultimaParcela': parcela_base,
        'ultimaParcela_formatado': format_currency(parcela_base),
        'valorTotal': valor_total_equipamentos,
        'valorTotal_formatado': format_currency(valor_total_equipamentos),
        'valorTotalFinal': valor_total_final,
        'valorTotalFinal_formatado': format_currency(valor_total_final),
        'desconto': float(registro.valor_desconto),
        'desconto_formatado': format_currency(registro.valor_desconto),
        'observacao': registro.observacoes,
        'tipoPagamento': registro.forma_pagamento,
        'nomeVendedor': registro.nome_vendedor,
        'nomeCNPJ': registro.documento if registro.tipo_documento == 'CNPJ' else '',
        'nomeCliente': registro.nome_cliente,
        'subtotalEquipamentos': valor_total_equipamentos,
        'subtotalEquipamentos_formatado': format_currency(valor_total_equipamentos),
        'valorFinalSemTaxa': float(registro.valor_avista),
        'valorFinalSemTaxa_formatado': format_currency(registro.valor_avista),
        'frete': float(registro.valor_frete),
        'frete_formatado': format_currency(registro.valor_frete),
        'validadeRelatorio': validade.strftime('%d/%m/%Y'),
        'dataGeracao': hoje.strftime('%d/%m/%Y'),
        'horaGeracao': hoje.strftime('%H:%M'),
    }

    html_string = render_to_string('api/pdf_simulador.html', template_data)
    pdf = html_to_pdf_weasyprint(html_string)

    if pdf:
        response = HttpResponse(pdf, content_type='application/pdf')
        # inline abre no navegador, attachment força o download
        response['Content-Disposition'] = f'inline; filename="Orcamento_{registro.id}.pdf"'
        return response

    return HttpResponse("Erro ao gerar PDF", status=500)