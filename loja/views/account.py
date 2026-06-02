import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import PerfilCliente, Pedido
from .utils import (
    get_carrinho_info,
    no_tracking_context,
    ratelimit,
    verificar_turnstile,
)

logger = logging.getLogger(__name__)


# ── CADASTRO ───────────────────────────────────────────────────────
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def cadastro(request):
    from django.conf import settings
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            context = {'qtd_carrinho': get_carrinho_info(request)}
            context.update(no_tracking_context(request, 'Criar conta - Barrs Store'))
            return render(request, 'cadastro.html', context)

        nome = request.POST.get('nome', '').strip()
        email = request.POST.get('email', '').strip().lower()
        senha = request.POST.get('senha', '')
        senha2 = request.POST.get('senha2', '')

        if senha != senha2:
            messages.error(request, 'As senhas não coincidem.')
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'Este e-mail já está cadastrado.')
        else:
            partes = nome.split()
            user_preview = User(
                username=email,
                email=email,
                first_name=partes[0] if partes else '',
                last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
            )
            try:
                validate_password(senha, user_preview)
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
            else:
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=senha,
                    first_name=partes[0] if partes else '',
                    last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
                )
                PerfilCliente.objects.create(user=user)
                login(request, user)
                messages.success(request, 'Conta criada com sucesso!')
                return redirect('minha_conta')

    context = {'qtd_carrinho': get_carrinho_info(request)}
    context.update(no_tracking_context(request, 'Criar conta - Barrs Store'))
    return render(request, 'cadastro.html', context)


# ── LOGIN ──────────────────────────────────────────────────────────
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def login_view(request):
    from django.conf import settings
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            context = {'qtd_carrinho': get_carrinho_info(request)}
            context.update(no_tracking_context(request, 'Login - Barrs Store'))
            return render(request, 'login.html', context)

        email = request.POST.get('email', '').strip().lower()
        senha = request.POST.get('senha', '')
        # Lookup case-insensitive: clientes legados podem ter username em maiusculas,
        # mas autenticamos com o username real armazenado no banco.
        usuario_existente = User.objects.filter(email__iexact=email).first()
        user = (
            authenticate(request, username=usuario_existente.username, password=senha)
            if usuario_existente else None
        )
        if user:
            login(request, user)
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=not settings.DEBUG
            ):
                return redirect(next_url)
            return redirect('minha_conta')
        else:
            messages.error(request, 'E-mail ou senha incorretos.')

    context = {'qtd_carrinho': get_carrinho_info(request)}
    context.update(no_tracking_context(request, 'Login - Barrs Store'))
    return render(request, 'login.html', context)


# ── LOGOUT ─────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('home')


# ── MINHA CONTA ────────────────────────────────────────────────────
@login_required(login_url='/login/')
def minha_conta(request):
    perfil, _ = PerfilCliente.objects.get_or_create(user=request.user)
    pedidos = Pedido.objects.filter(cliente=request.user).order_by('-criado_em')

    if request.method == 'POST':
        request.user.first_name = request.POST.get('primeiro_nome', '').strip()
        request.user.last_name = request.POST.get('ultimo_nome', '').strip()
        request.user.save()

        perfil.telefone = request.POST.get('telefone', '').strip()
        perfil.cep = request.POST.get('cep', '').strip()
        perfil.rua = request.POST.get('rua', '').strip()
        perfil.numero = request.POST.get('numero', '').strip()
        perfil.complemento = request.POST.get('complemento', '').strip()
        perfil.bairro = request.POST.get('bairro', '').strip()
        perfil.cidade = request.POST.get('cidade', '').strip()
        perfil.estado = request.POST.get('estado', '').strip()
        perfil.save()

        messages.success(request, 'Dados atualizados com sucesso!')
        return redirect('minha_conta')

    pedidos_total = pedidos.filter(
        status__in=['confirmado', 'enviado', 'entregue']
    ).aggregate(s=Sum('total'))['s'] or 0

    pedidos_andamento = pedidos.filter(
        status__in=['pendente', 'confirmado', 'enviado']
    ).count()

    context = {
        'perfil': perfil,
        'pedidos': pedidos,
        'pedidos_total': pedidos_total,
        'pedidos_andamento': pedidos_andamento,
        'qtd_carrinho': get_carrinho_info(request),
    }
    context.update(no_tracking_context(request, 'Minha conta - Barrs Store'))
    return render(request, 'minha_conta.html', context)


# ── DETALHE DO PEDIDO (cliente) ────────────────────────────────────
@login_required(login_url='/login/')
def detalhe_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, cliente=request.user)
    context = {
        'pedido': pedido,
        'qtd_carrinho': get_carrinho_info(request),
    }
    context.update(no_tracking_context(request, f'Pedido #{pedido.id} - Barrs Store'))
    return render(request, 'detalhe_pedido.html', context)
