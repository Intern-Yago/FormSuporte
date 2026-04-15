from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseBadRequest
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt

from django.contrib.auth.decorators import login_required

from Form_Suporte import settings
from painel.decorators import require_system_access

from .forms import SerialVCIForm, SerialVCIEditForm 
from .models import (
    SerialVCI,
    SerialFoto,
    Garantia,
    GarantiaFoto,
    GarantiaComentario,
    GarantiaComentarioFoto
)


# websocket broadcast
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def broadcast_update():
    """Envia aviso para TODOS os usuários atualizarem a tabela."""
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        "serial_vci_updates",
        {
            "type": "enviar_update",
            "content": {"mensagem": "atualizar_tabela"}
        }
    )

@login_required(login_url=settings.URL_LOGIN)
@require_system_access("seriais")
def lista_seriais(request):
    """Página inicial + busca ajax."""
    query = request.GET.get("q", "")
    page_number = request.GET.get("page", 1) 

    seriais = SerialVCI.objects.all().order_by("-id")

    if query:
        seriais = seriais.filter(
            Q(numero_vci__icontains=query) |
            Q(numero_tablet__icontains=query) |
            Q(numero_prog__icontains=query) |
            Q(cliente__icontains=query) |
            Q(email__icontains=query) |
            Q(telefone__icontains=query) |
            Q(pedido__icontains=query)
        )

    paginator = Paginator(seriais, 10)
    seriais_page = paginator.get_page(page_number) 

    # requisição AJAX → devolve só a tabela
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "serial_vci/_tabela.html", {
            "seriais": seriais_page,
            "query": query,
        })

    # requisição normal → página completa
    return render(request, "serial_vci/index.html", {
        "seriais": seriais_page,
        "query": query,
    })

def detalhes_serial(request, serial_id):
    serial = get_object_or_404(SerialVCI, id=serial_id)
    
    garantias = []
    for g in serial.garantias.all().order_by("-id"):

        comentarios = []
        for c in g.comentarios.all().order_by("id"):
            comentarios.append({
                "id": c.id,
                "texto": c.texto,
                "criado_em": c.criado_em.strftime("%d/%m/%Y %H:%M"),
                "fotos": [f.imagem.url for f in c.fotos.all()]
            })

        garantias.append({
            "id": g.id,
            "titulo": g.titulo,
            "descricao": g.descricao,
            "criado_em": g.criado_em.strftime("%d/%m/%Y %H:%M"),
            "fotos": [f.imagem.url for f in g.fotos.all()],
            "comentarios": comentarios         #  <<< AGORA EXISTE!!
        })

    return JsonResponse({
        "id": serial.id,
        "numero_vci": serial.numero_vci,
        "numero_tablet": serial.numero_tablet,
        "numero_prog": serial.numero_prog,
        "cliente": serial.cliente,
        "email": serial.email,
        "telefone": serial.telefone,
        "pedido": serial.pedido,
        "data": serial.data.strftime("%d/%m/%Y") if serial.data else None,
        "fotos": [f.imagem.url for f in serial.fotos.all()],
        "fotos_edicao": [
            {"id": f.id, "url": f.imagem.url}
            for f in serial.fotos.all()
        ],
        "garantias": garantias,
        "is_superuser": request.user.is_superuser,

    })


def adicionar_serial(request):
    """View para adicionar novo serial."""
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido")

    form = SerialVCIForm(request.POST, request.FILES)

    if not form.is_valid():
        return JsonResponse({"success": False, "errors": form.errors})

    serial = form.save()

    # salvar múltiplas imagens
    fotos = request.FILES.getlist("fotos")
    for foto in fotos:
        SerialFoto.objects.create(serial=serial, imagem=foto)

    broadcast_update()

    return JsonResponse({"success": True})


def editar_serial(request, serial_id):
    """View para editar SerialVCI (restrito aos campos VCI, Tablet, Prog e Fotos)."""
    if request.method != "POST":
        return HttpResponseBadRequest("Método inválido")

    serial = get_object_or_404(SerialVCI, id=serial_id)
    
    # Usa o SerialVCIEditForm que contém apenas os campos VCI, Tablet e Prog
    form = SerialVCIEditForm(request.POST, request.FILES, instance=serial)

    if not form.is_valid():
        return JsonResponse({"success": False, "errors": form.errors})

    # Salva apenas os campos VCI, Tablet, Prog 
    serial = form.save()

    # Adicionar novas imagens
    fotos = request.FILES.getlist("fotos")
    for foto in fotos:
        SerialFoto.objects.create(serial=serial, imagem=foto)

    broadcast_update()

    return JsonResponse({"success": True})


def remover_foto(request, foto_id):
    """View para remover uma foto existente (usada no modal de edição)."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método inválido"}, status=400)

    try:
        foto = get_object_or_404(SerialFoto, id=foto_id)
        # Remove o arquivo físico e do DB
        foto.imagem.delete(save=False) 
        foto.delete()
        
        broadcast_update()
        
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
    
@csrf_exempt
def add_garantia(request, serial_id):
    if request.method != "POST":
        return JsonResponse({"error": "Método inválido"}, status=400)

    serial = get_object_or_404(SerialVCI, id=serial_id)

    titulo = request.POST.get("titulo", "")
    descricao = request.POST.get("descricao", "")

    garantia = Garantia.objects.create(
        serial=serial,
        titulo=titulo,
        descricao=descricao,
    )

    for foto in request.FILES.getlist("fotos"):
        GarantiaFoto.objects.create(
            garantia=garantia,
            imagem=foto
        )

    return JsonResponse({"success": True})

def garantia_detalhes(request, garantia_id):
    garantia = get_object_or_404(Garantia, id=garantia_id)

    comentarios = []
    for c in garantia.comentarios.all().order_by("id"):
        comentarios.append({
            "id": c.id,
            "texto": c.texto,
            "criado_em": c.criado_em.strftime("%d/%m/%Y %H:%M"),
            "fotos": [f.imagem.url for f in c.fotos.all()]
        })

    return JsonResponse({
        "id": garantia.id,
        "titulo": garantia.titulo,
        "comentarios": comentarios
    })

@csrf_exempt
def add_comentario(request, garantia_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método inválido"}, status=400)

    garantia = get_object_or_404(Garantia, id=garantia_id)

    texto = request.POST.get("texto", "").strip()
    if not texto:
        return JsonResponse({"success": False, "error": "Comentário vazio"}, status=400)

    # cria comentário
    comentario = GarantiaComentario.objects.create(
        garantia=garantia,
        texto=texto
    )

    # adiciona fotos
    for foto in request.FILES.getlist("fotos"):
        GarantiaComentarioFoto.objects.create(
            comentario=comentario,
            imagem=foto
        )

    return JsonResponse({"success": True})

@csrf_exempt
def deletar_garantia(request, garantia_id):
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Método inválido"}, status=400)

    garantia = get_object_or_404(Garantia, id=garantia_id)

    # Remove fotos da garantia
    for foto in garantia.fotos.all():
        foto.imagem.delete(save=False)
        foto.delete()

    # Remove comentários + fotos de comentários
    for comentario in garantia.comentarios.all():
        for foto in comentario.fotos.all():
            foto.imagem.delete(save=False)
            foto.delete()
        comentario.delete()

    garantia.delete()

    return JsonResponse({"success": True})

@csrf_exempt
def delete_comentario(request, comentario_id):
    if not request.user.is_superuser:
        return JsonResponse({"success": False, "error": "Permissão negada"}, status=403)

    comentario = get_object_or_404(GarantiaComentario, id=comentario_id)

    # remover fotos físicas
    for foto in comentario.fotos.all():
        foto.imagem.delete(save=False)
        foto.delete()

    comentario.delete()

    return JsonResponse({"success": True})
