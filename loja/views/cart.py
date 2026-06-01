import logging
import time

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import (
    Carrinho, ItemCarrinho, Lead, Pedido, ItemPedido, PerfilCliente,
    Produto, TamanhoAnel, Cupom,
)
from ..validators import cpf_valido
from ..integrations.meta_capi import (
    send_add_to_cart_event,
    send_initiate_checkout_event,
)
from .utils import (
    apenas_digitos,
    aplicar_lead_no_carrinho,
    get_carrinho_info,
    noindex_context,
    ratelimit,
    salvar_lead_na_sessao,
    turnstile_error_json,
    verificar_turnstile,
)
from .emails import enviar_whatsapp_pedido

logger = logging.getLogger(__name__)


def _validar_form_checkout(request, carrinho):
    campos_obrigatorios = {
        'nome': 'Nome completo',
        'email': 'E-mail',
        'telefone': 'Celular',
        'cpf': 'CPF',
        'cep': 'CEP',
        'rua': 'Rua',
        'numero': 'Numero',
        'bairro': 'Bairro',
        'cidade': 'Cidade',
        'estado': 'Estado (UF)',
    }
    for campo, rotulo in campos_obrigatorios.items():
        if not request.POST.get(campo, '').strip():
            messages.error(request, f'Preencha o campo {rotulo}.')
            return None

    cpf_pedido = apenas_digitos(request.POST.get('cpf', ''))
    if len(cpf_pedido) != 11:
        messages.error(request, 'Informe um CPF valido com 11 numeros.')
        return None
    if not cpf_valido(cpf_pedido):
        messages.error(request, 'Informe um CPF valido.')
        return None

    # Frete deve vir da opção escolhida pelo comprador no Melhor Envio.
    frete_selecionado = request.POST.get('frete_valor', '').replace(',', '.').strip()
    if not frete_selecionado:
        messages.error(request, 'Calcule e selecione uma opção de frete no carrinho antes de finalizar.')
        return None
    try:
        frete = Decimal(frete_selecionado)
        if frete < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        messages.error(request, 'Não foi possível validar o frete selecionado. Calcule o frete novamente no carrinho.')
        return None

    subtotal = carrinho.total()
    desconto = Decimal('0')
    cupom_codigo = request.POST.get('cupom_codigo', '').strip().upper()
    cupom = None
    if cupom_codigo:
        cupom = Cupom.objects.filter(codigo__iexact=cupom_codigo).first()
        if not cupom:
            messages.error(request, 'Cupom nao encontrado.')
            return None
        # Para cupons de fidelidade: se o user nao esta logado, tenta localizar
        # pelo email digitado no formulario (caso de login durante o checkout).
        user_para_validar = request.user
        if not getattr(user_para_validar, 'is_authenticated', False):
            email_form = request.POST.get('email', '').strip().lower()
            if email_form:
                user_para_validar = User.objects.filter(email__iexact=email_form).first()
        valido, motivo = cupom.valido_para(subtotal, user=user_para_validar)
        if not valido:
            messages.error(request, motivo)
            return None
        desconto = cupom.calcular_desconto(subtotal, frete)

    try:
        frete_service_id = int(request.POST.get('frete_service_id') or 0) or None
    except (TypeError, ValueError):
        frete_service_id = None

    return {
        'nome': request.POST['nome'],
        'email': request.POST['email'].strip().lower(),
        'telefone': request.POST.get('telefone', '').strip(),
        'cpf': cpf_pedido,
        'cep': request.POST['cep'],
        'rua': request.POST['rua'],
        'numero': request.POST['numero'],
        'complemento': request.POST.get('complemento', '').strip(),
        'bairro': request.POST['bairro'],
        'cidade': request.POST['cidade'],
        'estado': request.POST.get('estado', 'SP'),
        'frete': frete,
        'frete_service_id': frete_service_id,
        'subtotal': subtotal,
        'desconto': desconto,
        'cupom': cupom,
        'total': subtotal - desconto + frete,
        'observacoes': request.POST.get('observacoes', '').strip()[:500],
    }


def _resolver_cliente(request, dados):
    if request.user.is_authenticated:
        return request.user

    email_pedido = dados['email']
    senha = request.POST.get('senha', '').strip()

    if not senha:
        messages.error(request, 'Digite sua senha para entrar ou criar sua conta antes de finalizar.')
        return None

    usuario_existente = User.objects.filter(email__iexact=email_pedido).first()
    if usuario_existente:
        user = authenticate(request, username=usuario_existente.username, password=senha)
        if not user:
            messages.error(request, 'Nao foi possivel validar suas credenciais. Confira os dados e tente novamente.')
            return None
        login(request, user)
    else:
        partes = dados['nome'].split()
        user_preview = User(
            username=email_pedido,
            email=email_pedido,
            first_name=partes[0] if partes else '',
            last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
        )
        try:
            validate_password(senha, user_preview)
        except ValidationError as exc:
            messages.error(request, ' '.join(exc.messages))
            return None
        user = User.objects.create_user(
            username=email_pedido,
            email=email_pedido,
            password=senha,
            first_name=partes[0] if partes else '',
            last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
        )
        login(request, user)

    perfil, _ = PerfilCliente.objects.get_or_create(user=user)
    perfil.telefone = dados['telefone']
    perfil.cep = dados['cep']
    perfil.rua = dados['rua']
    perfil.numero = dados['numero']
    perfil.complemento = dados['complemento']
    perfil.bairro = dados['bairro']
    perfil.cidade = dados['cidade']
    perfil.estado = dados['estado']
    perfil.save()
    return user


def _criar_pedido_com_itens(carrinho, itens, dados, cliente, utm):
    pedido = Pedido.objects.create(
        cliente=cliente,
        nome=dados['nome'],
        email=dados['email'],
        telefone=dados['telefone'],
        cpf=dados['cpf'],
        cep=dados['cep'],
        rua=dados['rua'],
        numero=dados['numero'],
        complemento=dados['complemento'],
        bairro=dados['bairro'],
        cidade=dados['cidade'],
        estado=dados['estado'],
        forma_pagamento='pix',
        subtotal=dados['subtotal'],
        desconto=dados['desconto'],
        cupom_codigo=dados['cupom'].codigo.upper() if dados['cupom'] else '',
        frete=dados['frete'],
        total=dados['total'],
        melhor_envio_service_id=dados['frete_service_id'],
        origem_utm=utm,
        observacoes=dados['observacoes'],
    )
    ItemPedido.objects.bulk_create([
        ItemPedido(
            pedido=pedido,
            produto=item.produto,
            nome_produto=item.produto.nome,
            quantidade=item.quantidade,
            preco_unitario=item.produto.preco,
            tamanho=item.tamanho,
        )
        for item in itens
    ])
    # Mantem o carrinho preservado no DB para recuperacao. Apenas desvincula da sessao.
    carrinho.email_cliente = dados['email']
    carrinho.save(update_fields=['email_cliente'])
    return pedido


def _notificar_novo_pedido(pedido):
    logger.info('[CHECKOUT] Pedido %s criado. Aguardando pagamento.', pedido.id)
    enviar_whatsapp_pedido(pedido)


def ver_carrinho(request):
    carrinho_id = request.session.get('carrinho_id')
    seo = noindex_context(request, 'Carrinho - Barrs Store')
    if not carrinho_id:
        context = {
            'itens': [],
            'total': 0,
            'qtd_carrinho': 0,
        }
        context.update(seo)
        return render(request, 'carrinho.html', context)

    try:
        carrinho = Carrinho.objects.get(id=carrinho_id)
    except Carrinho.DoesNotExist:
        request.session.pop('carrinho_id', None)
        context = {
            'itens': [],
            'total': 0,
            'qtd_carrinho': 0,
        }
        context.update(seo)
        return render(request, 'carrinho.html', context)

    context = {
        'itens': carrinho.itens.all(),
        'total': carrinho.total(),
        'qtd_carrinho': get_carrinho_info(request),
    }
    context.update(seo)
    return render(request, 'carrinho.html', context)


# ── ADICIONAR AO CARRINHO ──────────────────────────────────────────
@require_POST
@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def adicionar_carrinho(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    wants_json = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or 'application/json' in request.headers.get('accept', '')
    )
    if not produto.visivel or produto.estoque <= 0:
        if wants_json:
            return JsonResponse({'ok': False, 'erro': 'Este produto esta indisponivel no momento.'}, status=400)
        messages.error(request, 'Este produto esta indisponivel no momento.')
        return redirect('home')

    carrinho_id = request.session.get('carrinho_id')

    if carrinho_id:
        try:
            carrinho = Carrinho.objects.get(id=carrinho_id)
        except Carrinho.DoesNotExist:
            carrinho = Carrinho.objects.create()
            request.session['carrinho_id'] = carrinho.id
    else:
        carrinho = Carrinho.objects.create()
        request.session['carrinho_id'] = carrinho.id

    try:
        quantidade = max(1, int(request.POST.get('quantidade', 1)))
    except (TypeError, ValueError):
        quantidade = 1
    tamanho = request.POST.get('tamanho', '').strip()
    estoque_disponivel = produto.estoque
    if tamanho:
        tamanho_obj = TamanhoAnel.objects.filter(produto=produto, numero=tamanho).first()
        if not tamanho_obj or tamanho_obj.estoque <= 0:
            if wants_json:
                return JsonResponse({'ok': False, 'erro': 'Este tamanho esta indisponivel no momento.'}, status=400)
            messages.error(request, 'Este tamanho esta indisponivel no momento.')
            return redirect(produto.get_absolute_url())
        estoque_disponivel = min(estoque_disponivel, tamanho_obj.estoque)

    item, criado = ItemCarrinho.objects.get_or_create(
        carrinho=carrinho,
        produto=produto,
        tamanho=tamanho,
    )

    quantidade_atual = 0 if criado else item.quantidade
    quantidade_permitida = max(estoque_disponivel - quantidade_atual, 0)
    if quantidade_permitida <= 0:
        if wants_json:
            return JsonResponse({'ok': False, 'erro': 'Voce ja adicionou todo o estoque disponivel deste produto.'}, status=400)
        messages.error(request, 'Voce ja adicionou todo o estoque disponivel deste produto.')
        return redirect('carrinho')
    quantidade = min(quantidade, quantidade_permitida)

    if criado:
        item.quantidade = quantidade
    else:
        item.quantidade += quantidade
    item.save()
    aplicar_lead_no_carrinho(request, carrinho)
    carrinho.save(update_fields=['atualizado_em'])
    request.session['carrinho_id'] = carrinho.id
    request.session.modified = True
    request.session.save()

    # Meta CAPI AddToCart (server-side). Pixel ja disparou client-side com o mesmo event_id;
    # Meta deduplica os dois. Se o front nao enviou event_id (adblocker ou JS off), o CAPI cobre.
    try:
        event_id = request.POST.get('meta_event_id') or f'addtocart_{produto.id}_{int(time.time())}_{carrinho.id}'
        send_add_to_cart_event(produto, request, event_id)
    except Exception:
        logger.debug('[META CAPI] AddToCart silencioso (nao quebra fluxo de carrinho).', exc_info=True)

    if wants_json:
        return JsonResponse({
            'ok': True,
            'message': f'{produto.nome} adicionado ao carrinho.',
            'cart_count': get_carrinho_info(request),
        })

    messages.success(request, f'{produto.nome} adicionado ao carrinho.')

    next_url = (request.POST.get('next') or '').strip()
    allowed = {request.get_host()}
    require_https = request.is_secure()

    # Detalhe → volta para a pagina do produto com flag pra toast existente
    if next_url == 'detalhe':
        return redirect(produto.get_absolute_url() + '?added=1')
    # Explicito: ir para o carrinho
    if next_url == 'carrinho':
        return redirect('carrinho')
    # URL relativa segura → mantem o usuario no mesmo contexto (categoria/busca/ordem)
    if next_url.startswith('/') and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts=allowed, require_https=require_https,
    ):
        if '#' in next_url:
            base, frag = next_url.split('#', 1)
            sep = '&' if '?' in base else '?'
            return redirect(f'{base}{sep}added=1#{frag}')
        sep = '&' if '?' in next_url else '?'
        return redirect(f'{next_url}{sep}added=1')
    # Fallback: HTTP_REFERER do mesmo host
    referer = request.META.get('HTTP_REFERER', '')
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts=allowed, require_https=require_https,
    ):
        return redirect(referer)
    # Ultimo fallback
    return redirect('carrinho')


# ── REMOVER 1 UNIDADE ──────────────────────────────────────────────
@require_POST
def remover_item(request, item_id):
    carrinho_id = request.session.get('carrinho_id')
    item = get_object_or_404(ItemCarrinho, id=item_id, carrinho_id=carrinho_id)
    carrinho = item.carrinho
    if item.quantidade > 1:
        item.quantidade -= 1
        item.save()
    else:
        item.delete()
    carrinho.save(update_fields=['atualizado_em'])
    return redirect('carrinho')


# ── DELETAR ITEM INTEIRO ───────────────────────────────────────────
@require_POST
def deletar_item(request, item_id):
    carrinho_id = request.session.get('carrinho_id')
    item = get_object_or_404(ItemCarrinho, id=item_id, carrinho_id=carrinho_id)
    carrinho = item.carrinho
    item.delete()
    carrinho.save(update_fields=['atualizado_em'])
    return redirect('carrinho')


@require_POST
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def salvar_lead_footer(request):
    telefone = apenas_digitos(request.POST.get('telefone', ''))
    if len(telefone) < 10:
        return JsonResponse({'ok': False, 'erro': 'Informe um celular valido com DDD.'}, status=400)

    if not request.session.session_key:
        request.session.save()
    sessao_key = request.session.session_key

    if not Lead.objects.filter(telefone=telefone).exists():
        Lead.objects.create(
            nome='Lista exclusiva',
            telefone=telefone,
            aceita_whatsapp=True,
            origem='footer',
            sessao_key=sessao_key,
        )
        logger.info('[LEAD] Lead footer salvo: telefone=%s', telefone)

    return JsonResponse({'ok': True})


@require_POST
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def salvar_lead_cliente(request):
    nome = request.POST.get('nome', '').strip()
    telefone = apenas_digitos(request.POST.get('telefone', ''))

    if len(nome) < 2:
        return JsonResponse({'ok': False, 'erro': 'Informe seu nome.'}, status=400)
    if len(telefone) < 10:
        return JsonResponse({'ok': False, 'erro': 'Informe um WhatsApp valido.'}, status=400)

    salvar_lead_na_sessao(request, nome, telefone)
    carrinho_id = request.session.get('carrinho_id')
    if carrinho_id:
        try:
            aplicar_lead_no_carrinho(request, Carrinho.objects.get(id=carrinho_id))
        except Carrinho.DoesNotExist:
            request.session.pop('carrinho_id', None)

    # Garante que a sessão tenha key persistida antes de gravar o Lead.
    if not request.session.session_key:
        request.session.save()
    sessao_key = request.session.session_key

    if not Lead.objects.filter(sessao_key=sessao_key, telefone=telefone).exists():
        Lead.objects.create(
            nome=nome,
            telefone=telefone,
            aceita_whatsapp=True,
            origem='home',
            sessao_key=sessao_key,
        )
        logger.info('[LEAD] Lead salvo no banco: nome=%s telefone=%s', nome, telefone)

    logger.info('[LEAD] Nome e telefone capturados para atendimento via WhatsApp.')
    return JsonResponse({'ok': True, 'nome': nome, 'telefone': telefone})


@require_POST
@ratelimit(key='ip', rate='15/m', method='POST', block=True)
def salvar_contato_carrinho(request):
    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return JsonResponse({'ok': False, 'erro': 'Carrinho nao encontrado.'}, status=404)

    carrinho = get_object_or_404(Carrinho, id=carrinho_id)
    nome = request.POST.get('nome', '').strip()
    telefone = apenas_digitos(request.POST.get('telefone', ''))
    email = request.POST.get('email', '').strip().lower()
    if nome:
        carrinho.nome_cliente = nome
    carrinho.telefone_cliente = telefone
    carrinho.aceita_whatsapp = bool(telefone)
    if email and '@' in email:
        carrinho.email_cliente = email
    salvar_lead_na_sessao(request, nome or carrinho.nome_cliente, telefone)
    carrinho.save(update_fields=['nome_cliente', 'telefone_cliente', 'aceita_whatsapp', 'email_cliente', 'atualizado_em'])

    logger.info(
        '[CARRINHO] Contato salvo no carrinho %s. WhatsApp=%s email=%s',
        carrinho.id,
        carrinho.aceita_whatsapp,
        bool(carrinho.email_cliente),
    )
    return JsonResponse({'ok': True})


@require_POST
@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def aplicar_cupom_ajax(request):
    if not verificar_turnstile(request):
        return turnstile_error_json()

    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return JsonResponse({'ok': False, 'erro': 'Carrinho nao encontrado.'}, status=404)

    carrinho = get_object_or_404(Carrinho, id=carrinho_id)
    subtotal = carrinho.total()
    codigo = request.POST.get('cupom_codigo', '').strip().upper()

    if not codigo:
        return JsonResponse({'ok': False, 'erro': 'Digite um cupom.'}, status=400)

    cupom = Cupom.objects.filter(codigo__iexact=codigo).first()
    if not cupom:
        return JsonResponse({'ok': False, 'erro': 'Cupom nao encontrado.'}, status=404)

    valido, motivo = cupom.valido_para(subtotal, user=request.user)
    if not valido:
        return JsonResponse({'ok': False, 'erro': motivo}, status=400)

    desconto = cupom.calcular_desconto(subtotal)
    return JsonResponse({
        'ok': True,
        'codigo': cupom.codigo.upper(),
        'tipo': cupom.tipo,
        'desconto': float(desconto),
        'subtotal': float(subtotal),
    })


# ── CHECKOUT ───────────────────────────────────────────────────────
@ratelimit(key='ip', rate='8/m', method='POST', block=True)
def checkout(request):
    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return redirect('carrinho')

    carrinho = get_object_or_404(Carrinho, id=carrinho_id)
    # select_related evita N+1: itens sao iterados na validacao, no render
    # e na criacao do Pedido — todos acessam item.produto.{nome, preco}.
    itens = carrinho.itens.select_related('produto').all()

    if not itens:
        return redirect('carrinho')

    def render_checkout(perfil=None):
        frete_valor = request.POST.get('frete_valor') or request.GET.get('frete_valor', '')
        frete_nome = request.POST.get('frete_nome') or request.GET.get('frete_nome', '')
        frete_service_id = request.POST.get('frete_service_id') or request.GET.get('frete_service_id', '')
        # Meta CAPI InitiateCheckout server-side com mesmo event_id do Pixel client-side
        # (deduplicacao no Meta). So dispara no GET inicial; POST nao retransmite.
        meta_event_id = f'initcheckout_{carrinho.id}_{int(time.time())}'
        if request.method == 'GET':
            try:
                send_initiate_checkout_event(carrinho, request, meta_event_id)
            except Exception:
                logger.debug('[META CAPI] InitiateCheckout silencioso (nao quebra checkout).', exc_info=True)
        context = {
            'itens': itens,
            'total': carrinho.total(),
            'qtd_carrinho': get_carrinho_info(request),
            'perfil': perfil,
            'carrinho': carrinho,
            'lead_nome': request.session.get('lead_nome', ''),
            'lead_telefone': request.session.get('lead_telefone', ''),
            # Mantem o frete selecionado quando o checkout volta com erro de validacao.
            'frete_valor_selecionado': frete_valor,
            'frete_nome_selecionado': frete_nome,
            'frete_service_id_selecionado': frete_service_id,
            'meta_event_id': meta_event_id,
        }
        context.update(noindex_context(request, 'Checkout - Barrs Store'))
        return render(request, 'checkout.html', context)

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            return render_checkout()

        salvar_lead_na_sessao(
            request,
            request.POST.get('nome', ''),
            request.POST.get('telefone', ''),
        )
        aplicar_lead_no_carrinho(request, carrinho)

        for item in itens.select_related('produto'):
            if not item.produto or not item.produto.visivel or item.produto.estoque < item.quantidade:
                messages.error(request, f'O produto {item.produto.nome if item.produto else item.nome_produto} nao tem estoque suficiente.')
                return redirect('carrinho')
            if item.tamanho:
                tamanho = TamanhoAnel.objects.filter(produto=item.produto, numero=item.tamanho).first()
                if not tamanho or tamanho.estoque < item.quantidade:
                    messages.error(request, f'O tamanho {item.tamanho} de {item.produto.nome} nao tem estoque suficiente.')
                    return redirect('carrinho')

        dados = _validar_form_checkout(request, carrinho)
        if dados is None:
            return render_checkout()

        cliente = _resolver_cliente(request, dados)
        if cliente is None:
            return render_checkout()

        pedido = _criar_pedido_com_itens(carrinho, itens, dados, cliente, request.session.get('utm') or {})
        request.session.pop('carrinho_id', None)
        # E-mail "Finalize seu pagamento" e disparado pelo cron apos 20min,
        # evitando SPAM para quem fechou a aba logo em seguida.
        _notificar_novo_pedido(pedido)
        return redirect('confirmacao', pedido_id=pedido.id, token=pedido.access_token)

    perfil = None
    if request.user.is_authenticated:
        perfil, _ = PerfilCliente.objects.get_or_create(user=request.user)

    return render_checkout(perfil)
