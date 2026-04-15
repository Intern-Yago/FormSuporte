# views.py
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from rest_framework.authtoken.models import Token
from django.contrib.auth.decorators import login_required
@csrf_exempt
def index(request):
    context = {}

    # Se o usuário estiver logado, enviamos os dados dele
    if request.user.is_authenticated:
        token, _ = Token.objects.get_or_create(user=request.user)
        context['user_token'] = token.key
        context['user_name'] = request.user.get_full_name() or request.user.username
    else:
        # Se não estiver logado, enviamos vazio (o simulador usará os defaults dele)
        context['user_token'] = ""
        context['user_name'] = ""

    return render(request, 'simulador/index.html', context)
