import json
import logging
import os

import requests as http_requests
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse  # noqa: F401 — re-exportado para uso interno
from django.shortcuts import get_object_or_404

from ..models import Carrinho, Pedido

logger = logging.getLogger(__name__)

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    # Mantem o projeto funcionando localmente antes da dependencia ser instalada.
    def ratelimit(*args, **kwargs):
        def decorator(view_func):
            return view_func
        return decorator


def site_url(path=''):
    base = getattr(settings, 'SITE_URL', 'https://www.barrsstore.com.br').rstrip('/')
    if not path:
        return base
    path = str(path)
    if path.startswith(('http://', 'https://')):
        return path
    return f"{base}{path if path.startswith('/') else '/' + path}"


def seo_context(request, title, description, image_url='', robots='index, follow'):
    canonical_path = request.path
    absolute_image = site_url(image_url) if image_url else site_url('/static/loja/og-barrs-store.jpg')
    return {
        'seo_title': title,
        'seo_description': description,
        'seo_canonical': site_url(canonical_path),
        'seo_robots': robots,
        'seo_image': absolute_image,
    }


def json_ld_dumps(data):
    return (
        json.dumps(data, ensure_ascii=False)
        .replace('&', '\\u0026')
        .replace('<', '\\u003C')
        .replace('>', '\\u003E')
    )


def noindex_context(request, title, description='Pagina operacional da Barrs Store.'):
    return seo_context(request, title, description, robots='noindex, nofollow')


def no_tracking_context(request, title, description='Pagina operacional da Barrs Store.'):
    """Como noindex_context, mas tambem desativa Meta Pixel e Google Analytics.

    Use em paginas FORA do funil de compra (login, cadastro, minha conta,
    rastreamento, pagamento_falha) para nao poluir audiencias de campanha.
    """
    context = noindex_context(request, title, description)
    context['seo_no_tracking'] = True
    return context


def get_pedido_por_token(pedido_id, token):
    return get_object_or_404(Pedido, id=pedido_id, access_token=token)


def verificar_turnstile(request):
    """Valida Cloudflare Turnstile quando as chaves estiverem configuradas."""
    if not getattr(settings, 'TURNSTILE_REQUIRED', False):
        return True

    token = request.POST.get('cf-turnstile-response', '').strip()
    if not token:
        return False

    try:
        resposta = http_requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={
                'secret': settings.TURNSTILE_SECRET_KEY,
                'response': token,
                'remoteip': request.META.get('REMOTE_ADDR', ''),
            },
            timeout=6,
        )
        data = resposta.json()
        if data.get('success'):
            return True
        logger.warning('[TURNSTILE] Validacao recusada. codes=%s', data.get('error-codes'))
    except Exception as exc:
        logger.warning('[TURNSTILE] Falha ao validar desafio: %s', exc)
    return False


def turnstile_error_json():
    return JsonResponse({'ok': False, 'erro': 'Confirme a verificacao de seguranca e tente novamente.'}, status=400)


def apenas_digitos(valor):
    return ''.join(filter(str.isdigit, valor or ''))


def dominio_email_para_log(email):
    email = (email or '').strip()
    return email.split('@')[-1].lower() if '@' in email else ''


def resposta_externa_segura_para_log(response):
    texto = getattr(response, 'text', '') or ''
    return {
        'status_code': getattr(response, 'status_code', None),
        'ok': getattr(response, 'ok', False),
        'body_len': len(texto),
    }


def payload_pagamento_seguro_para_log(payment_data):
    """Mostra o essencial do pagamento sem expor token, CPF completo ou dados sensiveis."""
    payer = payment_data.get('payer') or {}
    identification = payer.get('identification') or {}
    cpf = str(identification.get('number') or '')
    email = payer.get('email') or ''
    safe_payer = {
        'email_domain': email.split('@')[-1] if '@' in email else '',
        'has_identification': bool(identification),
        'identification_type': identification.get('type'),
        'cpf_last4': cpf[-4:] if cpf else '',
        'has_phone': bool(payer.get('phone')),
    }
    return {
        'transaction_amount': payment_data.get('transaction_amount'),
        'payment_method_id': payment_data.get('payment_method_id'),
        'installments': payment_data.get('installments'),
        'issuer_id': payment_data.get('issuer_id'),
        'has_token': bool(payment_data.get('token')),
        'external_reference': payment_data.get('external_reference'),
        'notification_url': payment_data.get('notification_url'),
        'payer': safe_payer,
    }


def get_carrinho_info(request):
    carrinho_id = request.session.get('carrinho_id')
    qtd_carrinho = 0
    if carrinho_id:
        try:
            carrinho = Carrinho.objects.get(id=carrinho_id)
            qtd_carrinho = sum(item.quantidade for item in carrinho.itens.all())
        except Carrinho.DoesNotExist:
            request.session.pop('carrinho_id', None)
    return qtd_carrinho


def salvar_lead_na_sessao(request, nome, telefone):
    nome = (nome or '').strip()
    telefone = apenas_digitos(telefone)
    if nome:
        request.session['lead_nome'] = nome
    if telefone:
        request.session['lead_telefone'] = telefone
    if nome and len(telefone) >= 10:
        request.session['lead_capturado'] = True
    request.session.modified = True


def aplicar_lead_no_carrinho(request, carrinho):
    nome = request.session.get('lead_nome', '').strip()
    telefone = request.session.get('lead_telefone', '').strip()
    campos = []
    if nome and carrinho.nome_cliente != nome:
        carrinho.nome_cliente = nome
        campos.append('nome_cliente')
    if telefone and carrinho.telefone_cliente != telefone:
        carrinho.telefone_cliente = telefone
        carrinho.aceita_whatsapp = True
        campos.extend(['telefone_cliente', 'aceita_whatsapp'])
    if campos:
        campos.append('atualizado_em')
        carrinho.save(update_fields=campos)
