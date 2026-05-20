from django.shortcuts import render, redirect, get_object_or_404
from django.db import transaction
from django.db.models import Q, F
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from .models import Produto, TamanhoAnel, Carrinho, ItemCarrinho, Pedido, ItemPedido, PerfilCliente, Categoria, Cupom, EmailPendente
from .mercadopago_security import validar_assinatura_mercadopago
from .validators import cpf_valido
from .integrations.meta_capi import send_purchase_event
import mercadopago
import json
import requests as http_requests
import os
import logging
import uuid
import hashlib
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

EMAIL_LOGO_URL = 'https://res.cloudinary.com/dsw5fkmwp/image/upload/q_auto/f_auto/v1777401449/ChatGPT_Image_28_de_abr._de_2026_15_37_19_ovzkth.png'
EMAIL_BRAND_NAME = 'Barrs Store'

CAIXA_ENVIO = {
    'width': 11,
    'length': 16,
    'height': 6,
    'weight': 0.5,
}

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
    return f"{base}{path if path.startswith('/') else '/' + path}"


def pacote_envio_por_quantidade(total_itens):
    """Ajusta peso e altura da caixa sem alterar a embalagem padrao da loja."""
    total_itens = max(int(total_itens or 1), 1)
    peso = max(Decimal('0.20'), Decimal('0.10') * total_itens)
    altura_extra = max(total_itens - 1, 0) // 4
    return {
        'width': CAIXA_ENVIO['width'],
        'length': CAIXA_ENVIO['length'],
        'height': min(CAIXA_ENVIO['height'] + altura_extra, 18),
        'weight': float(peso),
    }


def seo_context(request, title, description, image_url='', robots='index, follow'):
    canonical_path = request.path
    absolute_image = image_url or site_url('/static/og-barrs-store.jpg')
    return {
        'seo_title': title,
        'seo_description': description,
        'seo_canonical': site_url(canonical_path),
        'seo_robots': robots,
        'seo_image': absolute_image,
    }


def noindex_context(request, title, description='Pagina operacional da Barrs Store.'):
    return seo_context(request, title, description, robots='noindex, nofollow')


def get_pedido_por_token(pedido_id, token):
    return get_object_or_404(Pedido, id=pedido_id, access_token=token)


def dados_pagador_mercadopago(pedido):
    """Monta os dados do pagador sem confiar em dados digitados no frontend."""
    telefone_limpo = "".join(filter(str.isdigit, pedido.telefone or ""))
    cpf_limpo = apenas_digitos(pedido.cpf)
    partes_nome = (pedido.nome or '').strip().split()

    payer = {
        "name": pedido.nome,
        "first_name": partes_nome[0] if partes_nome else pedido.nome,
        "last_name": " ".join(partes_nome[1:]) if len(partes_nome) > 1 else "",
        "email": pedido.email or os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com'),
    }
    if len(cpf_limpo) == 11:
        payer["identification"] = {
            "type": "CPF",
            "number": cpf_limpo,
        }
    if len(telefone_limpo) >= 10:
        payer["phone"] = {
            "area_code": telefone_limpo[:2],
            "number": telefone_limpo[2:],
        }
    if pedido.cep and pedido.rua and pedido.numero:
        payer["address"] = {
            "zip_code": apenas_digitos(pedido.cep),
            "street_name": pedido.rua,
            "street_number": pedido.numero,
            "neighborhood": pedido.bairro,
            "city": pedido.cidade,
            "federal_unit": pedido.estado,
        }
    return payer


def resumir_erro_mercadopago(payment):
    """Evita gravar dados sensiveis do payload completo do Mercado Pago nos logs."""
    causes = payment.get('cause') or []
    return {
        'message': payment.get('message'),
        'error': payment.get('error'),
        'status': payment.get('status'),
        'status_detail': payment.get('status_detail'),
        'cause': [
            {
                'code': cause.get('code'),
                'description': cause.get('description'),
            }
            for cause in causes[:3]
            if isinstance(cause, dict)
        ],
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


def enfileirar_email_pendente(payload, motivo='', pedido_id=None, tipo=''):
    destinatarios = payload.get('to') or [{}]
    destinatario = destinatarios[0] if destinatarios else {}
    if pedido_id and tipo:
        # Chave estavel: garante dedupe em retentativas do webhook MP, mesmo que o payload varie.
        dedupe_raw = f'pedido:{pedido_id}:tipo:{tipo}'
    else:
        dedupe_raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    dedupe_key = hashlib.sha256(dedupe_raw.encode('utf-8')).hexdigest()
    email_pendente, criado = EmailPendente.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            'destinatario_email': destinatario.get('email', ''),
            'destinatario_nome': destinatario.get('name', ''),
            'assunto': payload.get('subject', '')[:200],
            'payload': payload,
            'ultimo_erro': motivo[:1000],
        },
    )
    if not criado and email_pendente.status == 'enviado':
        return email_pendente
    if not criado and motivo:
        email_pendente.ultimo_erro = motivo[:1000]
        email_pendente.save(update_fields=['ultimo_erro', 'atualizado_em'])
    return email_pendente


def enviar_brevo_payload(payload, timeout=10):
    brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
    if not brevo_api_key:
        return False, 'BREVO_API_KEY nao configurada.', None
    try:
        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'accept': 'application/json', 'api-key': brevo_api_key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=timeout,
        )
        if resposta.status_code >= 400:
            return False, f'Brevo status {resposta.status_code}', resposta
        return True, '', resposta
    except Exception as exc:
        return False, str(exc), None


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


def baixar_estoque_pedido(pedido):
    """Baixa o estoque uma unica vez quando o pagamento e confirmado."""
    with transaction.atomic():
        pedido_lock = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if pedido_lock.estoque_baixado:
            logger.info('[ESTOQUE] Pedido %s ja teve estoque baixado. Ignorando duplicidade.', pedido_lock.id)
            return False

        for item in pedido_lock.itens.select_related('produto').all():
            produto = item.produto
            if not produto:
                continue

            if item.tamanho:
                tamanho = TamanhoAnel.objects.select_for_update().filter(
                    produto=produto,
                    numero=item.tamanho,
                ).first()
                if tamanho:
                    tamanho.estoque = max((tamanho.estoque or 0) - item.quantidade, 0)
                    tamanho.save(update_fields=['estoque'])

            produto_lock = Produto.objects.select_for_update().get(pk=produto.pk)
            produto_lock.estoque = max((produto_lock.estoque or 0) - item.quantidade, 0)
            produto_lock.save(update_fields=['estoque'])
            logger.info(
                '[ESTOQUE] Pedido %s baixou %s un. do produto %s. estoque_atual=%s visivel=%s',
                pedido_lock.id,
                item.quantidade,
                produto_lock.id,
                produto_lock.estoque,
                produto_lock.visivel,
            )

        pedido_lock.estoque_baixado = True
        pedido_lock.save(update_fields=['estoque_baixado'])
        pedido.estoque_baixado = True
        return True


def enviar_meta_purchase_pedido(pedido):
    """Envia Purchase para Meta CAPI uma unica vez por pedido aprovado."""
    with transaction.atomic():
        pedido_lock = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if pedido_lock.meta_purchase_sent:
            logger.info('[META CAPI] Purchase do pedido %s ja enviado. Ignorando duplicidade.', pedido_lock.id)
            return False

        enviado = send_purchase_event(pedido_lock)
        if enviado:
            pedido_lock.meta_purchase_sent = True
            pedido_lock.save(update_fields=['meta_purchase_sent'])
            pedido.meta_purchase_sent = True
        return enviado

def confirmar_pedido_pago(pedido):
    logger.info('[PAGAMENTO] Confirmando pedido %s. status_atual=%s', pedido.id, pedido.status)

    # Trava o pedido para garantir que status e cupom sao tocados uma unica vez,
    # mesmo se webhook MP for reentregue ou se o cliente abrir varias abas em paralelo.
    with transaction.atomic():
        pedido_lock = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if pedido_lock.status != 'confirmado':
            pedido_lock.status = 'confirmado'
            if pedido_lock.cupom_codigo:
                Cupom.objects.filter(codigo__iexact=pedido_lock.cupom_codigo).update(usado=F('usado') + 1)
            pedido_lock.save(update_fields=['status'])
        pedido = pedido_lock

    # Efeitos colaterais idempotentes (cada um tem flag/lock proprio).
    baixar_estoque_pedido(pedido)

    meta_enviado = enviar_meta_purchase_pedido(pedido)
    logger.info('[META CAPI] Purchase pedido %s enviado=%s', pedido.id, meta_enviado)

    if not pedido.email_confirmacao_enviado:
        enviado = enviar_email_confirmacao(pedido)
        logger.info('[PAGAMENTO] E-mail de confirmacao do pedido %s enviado=%s', pedido.id, enviado)
        if enviado:
            pedido.email_confirmacao_enviado = True
            pedido.save(update_fields=['email_confirmacao_enviado'])

    envio_criado = criar_envio_melhor_envio(pedido)
    logger.info('[PAGAMENTO] Melhor Envio pedido %s criado=%s', pedido.id, envio_criado)


def buscar_referencia_pedido_por_merchant_order(sdk, merchant_order_id):
    if not merchant_order_id:
        return ''

    order_info = sdk.merchant_order().get(merchant_order_id)
    if order_info.get("status", 500) >= 400:
        logger.warning('Falha ao consultar merchant_order Mercado Pago %s: %s', merchant_order_id, order_info)
        return ''

    order = order_info.get("response", {})
    return str(order.get("external_reference") or (order.get("metadata") or {}).get("pedido_id") or '')


def confirmar_pagamento_mercadopago(payment_id, pedido_id_fallback=''):
    if not payment_id or not settings.MERCADOPAGO_ACCESS_TOKEN:
        logger.warning(
            '[PAGAMENTO] Nao foi possivel consultar Mercado Pago. payment_id=%s token_configurado=%s',
            payment_id,
            bool(settings.MERCADOPAGO_ACCESS_TOKEN),
        )
        return False

    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    logger.info('[PAGAMENTO] Consultando pagamento Mercado Pago payment_id=%s fallback=%s', payment_id, pedido_id_fallback)
    payment_info = sdk.payment().get(payment_id)
    if payment_info.get("status", 500) >= 400:
        logger.warning('Falha ao consultar pagamento Mercado Pago %s: %s', payment_id, payment_info)
        return False

    payment = payment_info.get("response", {})

    pedido_id = (
        payment.get("external_reference")
        or (payment.get("metadata") or {}).get("pedido_id")
        or pedido_id_fallback
    )
    if not pedido_id:
        merchant_order_id = (
            (payment.get("order") or {}).get("id")
            or payment.get("merchant_order_id")
        )
        logger.info('[PAGAMENTO] Pagamento %s sem pedido direto. Buscando via merchant_order=%s', payment_id, merchant_order_id)
        pedido_id = buscar_referencia_pedido_por_merchant_order(sdk, merchant_order_id)

    status = payment.get("status")
    status_detail = payment.get("status_detail")
    payment_method_id = payment.get("payment_method_id")
    payment_type_id = payment.get("payment_type_id")
    logger.info(
        '[PAGAMENTO] Mercado Pago retornou payment_id=%s pedido_id=%s status=%s detail=%s metodo=%s tipo=%s',
        payment_id,
        pedido_id,
        status,
        status_detail,
        payment_method_id,
        payment_type_id,
    )

    if not pedido_id:
        logger.warning(
            'Mercado Pago sem referencia de pedido no pagamento %s. status=%s order=%s metadata=%s',
            payment_id,
            status,
            payment.get("order"),
            payment.get("metadata"),
        )
        return False

    try:
        pedido = Pedido.objects.get(id=pedido_id)
    except Pedido.DoesNotExist:
        logger.warning('Pedido %s informado pelo Mercado Pago nao existe.', pedido_id)
        return False

    if status == "approved":
        confirmar_pedido_pago(pedido)
        return True
    if status == "pending":
        if pedido.status != "confirmado":
            pedido.status = "pendente"
            pedido.save(update_fields=['status'])
            logger.info('[PAGAMENTO] Pedido %s marcado como pendente. detail=%s', pedido.id, status_detail)
        return True
    if status in ["cancelled", "rejected"]:
        pedido.status = "cancelado"
        pedido.save(update_fields=['status'])
        logger.warning('[PAGAMENTO] Pedido %s cancelado/rejeitado. status=%s detail=%s', pedido.id, status, status_detail)
        return True

    logger.info('Pagamento Mercado Pago %s recebido com status %s detail=%s.', payment_id, status, status_detail)
    return False


def confirmar_merchant_order_mercadopago(merchant_order_id):
    if not merchant_order_id or not settings.MERCADOPAGO_ACCESS_TOKEN:
        logger.warning(
            '[PAGAMENTO] Nao foi possivel consultar merchant_order. merchant_order_id=%s token_configurado=%s',
            merchant_order_id,
            bool(settings.MERCADOPAGO_ACCESS_TOKEN),
        )
        return False

    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    logger.info('[PAGAMENTO] Consultando merchant_order Mercado Pago id=%s', merchant_order_id)
    order_info = sdk.merchant_order().get(merchant_order_id)
    if order_info.get("status", 500) >= 400:
        logger.warning('Falha ao consultar merchant_order Mercado Pago %s: %s', merchant_order_id, order_info)
        return False

    order = order_info.get("response", {})
    pedido_id_fallback = str(order.get("external_reference") or (order.get("metadata") or {}).get("pedido_id") or '')
    pagamentos = order.get("payments") or []
    logger.info(
        '[PAGAMENTO] Merchant order %s retornou external_reference=%s status=%s pagamentos=%s',
        merchant_order_id,
        pedido_id_fallback,
        order.get("status"),
        len(pagamentos),
    )
    confirmou = False
    for pagamento in pagamentos:
        payment_id = pagamento.get("id")
        if payment_id:
            confirmou = confirmar_pagamento_mercadopago(payment_id, pedido_id_fallback=pedido_id_fallback) or confirmou

    if not pagamentos:
        logger.info(
            'Merchant order Mercado Pago %s ainda sem pagamentos vinculados. external_reference=%s status=%s',
            merchant_order_id,
            pedido_id_fallback,
            order.get("status"),
        )
    return confirmou


def apenas_digitos(valor):
    return ''.join(filter(str.isdigit, valor or ''))


def melhor_envio_headers():
    token = os.environ.get('MELHOR_ENVIO_TOKEN', '').strip()
    if not token:
        return None
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'BarrsStore contato.barrsstore@gmail.com',
    }


def melhor_envio_base_url():
    return os.environ.get('MELHOR_ENVIO_BASE_URL', 'https://melhorenvio.com.br').rstrip('/')


def inferir_servico_melhor_envio(pedido):
    if pedido.melhor_envio_service_id:
        return pedido.melhor_envio_service_id
    nome = (pedido.melhor_envio_status or '').upper()
    if 'SEDEX' in nome:
        return 2
    return 1


def criar_envio_melhor_envio(pedido):
    """Insere o envio no carrinho do Melhor Envio para conferencia manual."""
    if pedido.melhor_envio_order_id:
        return True

    headers = melhor_envio_headers()
    if not headers:
        pedido.melhor_envio_erro = 'MELHOR_ENVIO_TOKEN nao configurado.'
        pedido.save(update_fields=['melhor_envio_erro'])
        return False

    service_id = inferir_servico_melhor_envio(pedido)
    subtotal_declarado = max(pedido.subtotal - pedido.desconto, Decimal('1.00'))
    itens_pedido = list(pedido.itens.all())
    pacote = pacote_envio_por_quantidade(sum(item.quantidade for item in itens_pedido))

    payload = {
        'service': int(service_id),
        'from': {
            'name': os.environ.get('ME_REMETENTE_NOME', 'Sabrina Almeida'),
            'phone': apenas_digitos(os.environ.get('ME_REMETENTE_TELEFONE', '11913225256')),
            'email': os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com'),
            'address': os.environ.get('ME_REMETENTE_RUA', 'Rua Equestre'),
            'number': os.environ.get('ME_REMETENTE_NUMERO', '170'),
            'district': os.environ.get('ME_REMETENTE_BAIRRO', 'Fazenda Aricanduva'),
            'city': os.environ.get('ME_REMETENTE_CIDADE', 'Sao Paulo'),
            'country_id': 'BR',
            'postal_code': apenas_digitos(os.environ.get('ME_REMETENTE_CEP', '08275700')),
            'state_abbr': os.environ.get('ME_REMETENTE_ESTADO', 'SP'),
        },
        'to': {
            'name': pedido.nome,
            'phone': apenas_digitos(pedido.telefone) or apenas_digitos(os.environ.get('ME_REMETENTE_TELEFONE', '11913225256')),
            'document': apenas_digitos(pedido.cpf),
            'email': pedido.email,
            'address': pedido.rua,
            'complement': pedido.complemento,
            'number': pedido.numero,
            'district': pedido.bairro,
            'city': pedido.cidade,
            'country_id': 'BR',
            'postal_code': apenas_digitos(pedido.cep),
            'state_abbr': pedido.estado.upper(),
        },
        'products': [
            {
                'name': item.nome_produto[:80],
                'quantity': str(item.quantidade),
                'unitary_value': str(item.preco_unitario),
            }
            for item in itens_pedido
        ],
        'volumes': [pacote],
        'options': {
            'insurance_value': float(subtotal_declarado),
            'receipt': False,
            'own_hand': False,
            'reverse': False,
            'non_commercial': True,
        },
    }

    try:
        resposta = http_requests.post(
            f'{melhor_envio_base_url()}/api/v2/me/cart',
            headers=headers,
            json=payload,
            timeout=15,
        )
        texto = resposta.text[:1000]
        logger.info('[ME] Criar envio pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta))

        if resposta.status_code >= 400:
            pedido.melhor_envio_status = 'erro'
            pedido.melhor_envio_erro = texto
            pedido.save(update_fields=['melhor_envio_status', 'melhor_envio_erro'])
            return False

        data = resposta.json()
        pedido.melhor_envio_order_id = str(data.get('id') or data.get('order_id') or data.get('protocol') or '')
        pedido.melhor_envio_service_id = service_id
        pedido.melhor_envio_status = 'no_carrinho'
        pedido.melhor_envio_erro = ''
        pedido.save(update_fields=[
            'melhor_envio_order_id',
            'melhor_envio_service_id',
            'melhor_envio_status',
            'melhor_envio_erro',
        ])
        return True
    except Exception as exc:
        pedido.melhor_envio_status = 'erro'
        pedido.melhor_envio_erro = str(exc)
        pedido.save(update_fields=['melhor_envio_status', 'melhor_envio_erro'])
        logger.exception('Erro ao criar envio Melhor Envio do pedido %s: %s', pedido.id, exc)
        return False



# ── E-MAIL: CONFIRMAÇÃO DE PEDIDO VIA BREVO ─────────────────────
def _brevo_sender():
    return {
        'name': os.environ.get('BREVO_FROM_NAME', 'Barrs Store | Atendimento').strip(),
        'email': os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip(),
    }


def _email_button(texto, url, cor='#738269'):
    return f"""
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto">
        <tr>
          <td bgcolor="{cor}" style="border-radius:999px;background:{cor};box-shadow:0 10px 22px rgba(83,98,76,0.18)">
            <a href="{url}" style="display:inline-block;padding:14px 26px;border-radius:999px;color:#ffffff;text-decoration:none;font-family:Montserrat,Arial,sans-serif;font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase">
              {texto}
            </a>
          </td>
        </tr>
      </table>
    """


def _email_order_summary(pedido):
    itens_html = ''.join([
        f"""
        <tr>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#3D342C;font-size:14px;line-height:1.35">
            <strong style="font-family:Georgia,'Times New Roman',serif;font-size:15px">{item.nome_produto}</strong>
            {f'<div style="color:#9E9488;font-size:12px;margin-top:3px">Tam. {item.tamanho}</div>' if getattr(item, 'tamanho', '') else ''}
          </td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#6B5E53;font-size:13px;text-align:center">{item.quantidade}</td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#738269;font-size:14px;font-weight:700;text-align:right">R$ {item.preco_unitario}</td>
        </tr>
        """
        for item in pedido.itens.all()
    ])
    frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Grátis"
    desconto_html = ''
    if pedido.desconto > 0:
        desconto_html = f"""
        <tr>
          <td colspan="2" style="padding-top:10px;color:#9E9488;font-size:13px">Desconto {pedido.cupom_codigo}</td>
          <td style="padding-top:10px;color:#738269;font-size:13px;font-weight:700;text-align:right">- R$ {pedido.desconto}</td>
        </tr>
        """
    return f"""
      <div style="background:#FBFAF7;border:1px solid #E8E3D8;border-radius:18px;padding:20px;margin:24px 0">
        <p style="margin:0 0 14px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Resumo do pedido #{pedido.id}</p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse">
          <tr>
            <th align="left" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Produto</th>
            <th align="center" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Qtd</th>
            <th align="right" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Valor</th>
          </tr>
          {itens_html}
          <tr>
            <td colspan="2" style="padding-top:14px;color:#9E9488;font-size:13px">Subtotal</td>
            <td style="padding-top:14px;color:#6B5E53;font-size:13px;text-align:right">R$ {pedido.subtotal}</td>
          </tr>
          <tr>
            <td colspan="2" style="padding-top:8px;color:#9E9488;font-size:13px">Frete</td>
            <td style="padding-top:8px;color:#6B5E53;font-size:13px;text-align:right">{frete_texto}</td>
          </tr>
          {desconto_html}
          <tr>
            <td colspan="2" style="padding-top:12px;color:#3D2D20;font-size:16px;font-weight:700">Total</td>
            <td style="padding-top:12px;color:#738269;font-size:17px;font-weight:800;text-align:right">R$ {pedido.total}</td>
          </tr>
        </table>
      </div>
    """


def _email_address_block(pedido):
    return f"""
      <div style="background:#F5F2EC;border-radius:16px;padding:18px;margin:20px 0">
        <p style="margin:0 0 10px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Entrega</p>
        <p style="margin:0;color:#6B5E53;font-size:14px;line-height:1.7">
          {pedido.rua}, {pedido.numero}{f" - {pedido.complemento}" if pedido.complemento else ""}<br>
          {pedido.bairro} - {pedido.cidade}/{pedido.estado}<br>
          CEP {pedido.cep}
        </p>
      </div>
    """


def _email_wrapper(titulo, corpo_html, preheader=''):
    preheader_html = preheader or titulo
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    @media only screen and (max-width: 620px) {{
      .email-shell {{ width: 100% !important; margin: 0 !important; border-radius: 0 !important; }}
      .email-pad {{ padding-left: 22px !important; padding-right: 22px !important; }}
      .email-title {{ font-size: 28px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#F5F2EC;font-family:Montserrat,Arial,sans-serif;color:#6B5E53">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{preheader_html}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#F5F2EC">
    <tr>
      <td align="center" style="padding:28px 12px">
        <table role="presentation" class="email-shell" width="600" cellspacing="0" cellpadding="0" border="0" style="width:600px;max-width:600px;background:#FFFFFF;border-radius:24px;overflow:hidden;border:1px solid #E8E3D8;box-shadow:0 18px 52px rgba(61,45,32,0.10)">
          <tr>
            <td class="email-pad" style="padding:30px 38px;background:linear-gradient(135deg,#6F7E66 0%,#8A947C 100%);text-align:center">
              <img src="{EMAIL_LOGO_URL}" width="58" height="58" alt="Barrs Store" style="display:block;margin:0 auto 12px;border-radius:50%">
              <p style="margin:0 0 6px;color:#E8EDE3;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase">Barrs Store</p>
              <h1 class="email-title" style="margin:0;color:#FFFFFF;font-family:Georgia,'Times New Roman',serif;font-size:32px;line-height:1.02;font-weight:700;letter-spacing:-0.03em">{titulo}</h1>
            </td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:34px 38px 30px">
              {corpo_html}
            </td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:22px 38px;background:#FBFAF7;border-top:1px solid #E8E3D8;text-align:center">
              <p style="margin:0 0 8px;color:#9E9488;font-size:12px;line-height:1.6">Dúvidas sobre seu pedido? Fale com a gente pelo WhatsApp.</p>
              <p style="margin:0;color:#9E9488;font-size:11px;line-height:1.6">© 2026 Barrs Store · <a href="https://www.barrsstore.com.br" style="color:#738269;text-decoration:none">barrsstore.com.br</a></p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def enviar_email_confirmacao(pedido):
    """Envia e-mail de confirmacao para o cliente via Brevo."""
    try:
        itens_html = ''.join([
            f"""<tr>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#6B5E53">{item.nome_produto}</td>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#6B5E53;text-align:center">{item.quantidade}</td>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#8A947C;text-align:right;font-weight:600">R$ {item.preco_unitario}</td>
            </tr>"""
            for item in pedido.itens.all()
        ])

        frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Grátis 🎉"
        desconto_html = ''
        if pedido.desconto > 0:
            desconto_html = f"""
                  <tr>
                    <td colspan="2" style="padding-top:8px;font-size:13px;color:#9E9488">Desconto {pedido.cupom_codigo}</td>
                    <td style="padding-top:8px;font-size:13px;color:#8A947C;text-align:right;font-weight:600">- R$ {pedido.desconto}</td>
                  </tr>"""

        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;background:#F5F2EC;font-family:'Arial',sans-serif">
          <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(107,94,83,0.08)">
            <div style="background:#8A947C;padding:32px 40px;text-align:center">
              <h1 style="color:#fff;font-size:24px;margin:0;letter-spacing:-0.5px">Barrs Store</h1>
              <p style="color:#E8EDE3;font-size:13px;margin:8px 0 0">Acessórios modernos e exclusivos</p>
            </div>
            <div style="padding:40px">
              <div style="text-align:center;margin-bottom:28px">
                <div style="width:64px;height:64px;background:#E8EDE3;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;margin-bottom:16px">{_email_icon("check", 30)}</div>
                <h2 style="color:#3d2d20;font-size:22px;margin:0 0 8px">Pedido confirmado!</h2>
                <p style="color:#9E9488;font-size:14px;margin:0">Obrigada pela sua compra, <strong style="color:#6B5E53">{pedido.nome}</strong>!</p>
              </div>
              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">PEDIDO #{pedido.id}</p>
                <table style="width:100%;border-collapse:collapse">
                  <tr>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:left;padding-bottom:8px">Produto</th>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:center;padding-bottom:8px">Qtd</th>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:right;padding-bottom:8px">Valor</th>
                  </tr>
                  {itens_html}
                  <tr>
                    <td colspan="2" style="padding-top:12px;font-size:13px;color:#9E9488">Frete</td>
                    <td style="padding-top:12px;font-size:13px;color:#8A947C;text-align:right;font-weight:600">{frete_texto}</td>
                  </tr>
                  {desconto_html}
                  <tr>
                    <td colspan="2" style="padding-top:8px;font-size:15px;font-weight:700;color:#3d2d20">Total</td>
                    <td style="padding-top:8px;font-size:15px;font-weight:700;color:#8A947C;text-align:right">R$ {pedido.total}</td>
                  </tr>
                </table>
              </div>
              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">ENDEREÇO DE ENTREGA</p>
                <p style="font-size:14px;color:#6B5E53;margin:0;line-height:1.7">
                  {pedido.rua}, {pedido.numero}{f" — {pedido.complemento}" if pedido.complemento else ""}<br>
                  {pedido.bairro} — {pedido.cidade}/{pedido.estado}<br>
                  CEP {pedido.cep}
                </p>
              </div>
              <div style="text-align:center;padding:20px 0;border-top:1px solid #D9D3C7">
                <p style="font-size:13px;color:#9E9488;margin:0 0 16px">Dúvidas? Fale conosco pelo WhatsApp</p>
                <a href="https://wa.me/5511913225256" style="display:inline-block;padding:12px 28px;background:#25d366;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">WhatsApp</a>
              </div>
            </div>
            <div style="background:#F5F2EC;padding:20px 40px;text-align:center">
              <p style="font-size:12px;color:#9E9488;margin:0">© 2026 Barrs Store • barrsstore.com.br</p>
            </div>
          </div>
        </body>
        </html>
        """

        brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
        if not brevo_api_key:
            logger.warning('BREVO_API_KEY nao configurada. E-mail do pedido %s nao foi enviado.', pedido.id)
            return False

        logger.info('[BREVO] Iniciando envio do pedido %s. email_domain=%s', pedido.id, dominio_email_para_log(pedido.email))
        brevo_from_email = os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip()
        brevo_admin_email = os.environ.get('BREVO_ADMIN_EMAIL', brevo_from_email).strip()
        payload = {
            'sender': {
                'name': 'Barrs Store',
                'email': brevo_from_email,
            },
            'to': [{'email': pedido.email, 'name': pedido.nome}],
            'subject': f'Pedido #{pedido.id} confirmado — Barrs Store',
            'htmlContent': html,
        }
        if brevo_admin_email and brevo_admin_email.lower() != pedido.email.lower():
            payload['bcc'] = [{'email': brevo_admin_email, 'name': 'Barrs Store'}]

        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'accept': 'application/json',
                'api-key': brevo_api_key,
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=10,
        )
        logger.info('[BREVO] Resposta pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta))
        if resposta.status_code >= 400:
            logger.warning(
                'Brevo recusou o e-mail do pedido %s: %s',
                pedido.id,
                resposta_externa_segura_para_log(resposta),
            )
            return False
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail Brevo do pedido %s: %s', pedido.id, exc)
        return False


def enviar_email_pagamento_pendente(pedido):
    """Envia um lembrete simples com link para finalizar o pagamento."""
    if pedido.email_pagamento_pendente_enviado:
        return True
    try:
        brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
        if not brevo_api_key:
            logger.warning('BREVO_API_KEY nao configurada. E-mail de pagamento pendente do pedido %s nao foi enviado.', pedido.id)
            return False
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        brevo_from_email = os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip()
        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'accept': 'application/json', 'api-key': brevo_api_key, 'Content-Type': 'application/json'},
            json={
                'sender': {'name': 'Barrs Store', 'email': brevo_from_email},
                'to': [{'email': pedido.email, 'name': pedido.nome}],
                'subject': f'Finalize o pagamento do pedido #{pedido.id} - Barrs Store',
                'htmlContent': f"""
                <div style="font-family:Arial,sans-serif;background:#F5F2EC;padding:28px">
                  <div style="max-width:560px;margin:auto;background:#fff;border-radius:14px;padding:28px;color:#6B5E53">
                    <h2 style="color:#3d2d20;margin-top:0">Seu pedido foi reservado</h2>
                    <p>Oi, {pedido.nome}! Recebemos seu pedido #{pedido.id} e estamos aguardando o pagamento.</p>
                    <p><strong>Total:</strong> R$ {pedido.total}</p>
                    <a href="{link_pagamento}" style="display:inline-block;background:#8A947C;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600">Finalizar pagamento</a>
                    <p style="font-size:13px;color:#9E9488;margin-top:22px">Se voce ja pagou, pode ignorar este e-mail. A confirmacao e automatica.</p>
                  </div>
                </div>
                """,
            },
            timeout=10,
        )
        logger.info('[BREVO] Pagamento pendente pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta))
        if resposta.status_code < 400:
            pedido.email_pagamento_pendente_enviado = True
            pedido.save(update_fields=['email_pagamento_pendente_enviado'])
            return True
        logger.warning(
            'Brevo recusou o e-mail de pagamento pendente do pedido %s: %s',
            pedido.id,
            resposta_externa_segura_para_log(resposta),
        )
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de pagamento pendente do pedido %s: %s', pedido.id, exc)
    return False


def enviar_email_rastreio(pedido):
    """Envia o codigo de rastreio ao cliente quando o pedido for enviado."""
    if not pedido.codigo_rastreio:
        return False
    try:
        brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
        if not brevo_api_key:
            logger.warning('BREVO_API_KEY nao configurada. E-mail de rastreio do pedido %s nao foi enviado.', pedido.id)
            return False
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'accept': 'application/json', 'api-key': brevo_api_key, 'Content-Type': 'application/json'},
            json={
                'sender': {'name': 'Barrs Store', 'email': os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com')},
                'to': [{'email': pedido.email, 'name': pedido.nome}],
                'subject': f'Seu pedido #{pedido.id} foi enviado - Barrs Store',
                'htmlContent': f"""
                <div style="font-family:Arial,sans-serif;background:#F5F2EC;padding:28px">
                  <div style="max-width:560px;margin:auto;background:#fff;border-radius:14px;padding:28px;color:#6B5E53">
                    <h2 style="color:#3d2d20;margin-top:0">Seu pedido foi enviado</h2>
                    <p>Oi, {pedido.nome}! O pedido #{pedido.id} já foi enviado.</p>
                    <p><strong>Código de rastreio:</strong> {pedido.codigo_rastreio}</p>
                    <p><strong>Transportadora:</strong> {transportadora}</p>
                    <p>Você pode acompanhar a entrega pelo botão abaixo. Se for Loggi, cole o código de rastreio no site da transportadora.</p>
                    <a href="{rastreio_url}" style="display:inline-block;background:#8A947C;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600">Acompanhar entrega</a>
                    <p style="font-size:13px;color:#9E9488;margin-top:18px">Link de rastreio: <a href="{rastreio_url}" style="color:#8A947C">{rastreio_url}</a></p>
                  </div>
                </div>
                """,
            },
            timeout=10,
        )
        logger.info('[BREVO] Rastreio pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta))
        if resposta.status_code >= 400:
            logger.warning(
                'Brevo recusou o e-mail de rastreio do pedido %s: %s',
                pedido.id,
                resposta_externa_segura_para_log(resposta),
            )
            return False
        pedido.email_rastreio_enviado = True
        pedido.save(update_fields=['email_rastreio_enviado'])
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de rastreio do pedido %s: %s', pedido.id, exc)
        return False


# ── HELPERS DE EMAIL ──────────────────────────────────────────────
def _brevo_send(assunto, html, destinatario_email, destinatario_nome):
    payload = _brevo_payload(destinatario_email, destinatario_nome, assunto, html)
    ok, erro, resposta = enviar_brevo_payload(payload)
    if ok:
        return True
    enfileirar_email_pendente(payload, erro)
    if resposta is not None:
        logger.warning('[BREVO] E-mail "%s" enfileirado: %s', assunto, resposta_externa_segura_para_log(resposta))
    else:
        logger.warning('[BREVO] E-mail "%s" enfileirado. email_domain=%s erro=%s', assunto, dominio_email_para_log(destinatario_email), erro)
    return False


def _email_wrapper(titulo, corpo_html):
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#F5F2EC;font-family:Arial,sans-serif">
  <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(107,94,83,0.08)">
    <div style="background:#8A947C;padding:28px 40px;text-align:center">
      <p style="color:#E8EDE3;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin:0 0 6px">Barrs Store</p>
      <h1 style="color:#fff;font-size:21px;margin:0;font-weight:600;letter-spacing:-0.3px">{titulo}</h1>
    </div>
    <div style="padding:36px 40px">{corpo_html}</div>
    <div style="background:#F5F2EC;padding:20px 40px;text-align:center;border-top:1px solid #E8EDE3">
      <p style="font-size:11px;color:#9E9488;margin:0">© 2026 Barrs Store · <a href="https://www.barrsstore.com.br" style="color:#8A947C;text-decoration:none">barrsstore.com.br</a></p>
      <p style="font-size:11px;color:#9E9488;margin:6px 0 0">Dúvidas? <a href="https://wa.me/5511913225256" style="color:#8A947C;text-decoration:none">WhatsApp</a></p>
    </div>
  </div>
</body></html>"""


def _btn(texto, url, cor='#8A947C'):
    return f'<a href="{url}" style="display:inline-block;padding:13px 28px;background:{cor};color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">{texto}</a>'


def _paragrafo(texto):
    return f'<p style="font-size:14px;color:#6B5E53;line-height:1.7;margin:0 0 16px">{texto}</p>'


def _email_icon(nome='gem', size=22, color='#738269'):
    icons = {
        'gem': '<path d="M6 3h12l4 6-10 12L2 9l4-6Z"/><path d="M2 9h20"/><path d="m6 3 6 18 6-18"/><path d="M6 3 2 9"/><path d="m18 3 4 6"/>',
        'heart': '<path d="M19.5 12.6 12 20l-7.5-7.4a5 5 0 0 1 7.1-7.1l.4.4.4-.4a5 5 0 0 1 7.1 7.1Z"/>',
        'truck': '<path d="M3 7h11v10H3z"/><path d="M14 10h4l3 3v4h-7z"/><circle cx="7" cy="19" r="2"/><circle cx="18" cy="19" r="2"/>',
        'message': '<path d="M21 12a8 8 0 0 1-8 8H7l-4 3 1.4-5.2A8 8 0 1 1 21 12Z"/>',
        'bag': '<path d="M6 8h12l-1 13H7L6 8Z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
        'check': '<path d="M20 6 9 17l-5-5"/>',
        'leaf': '<path d="M5 19c9 0 14-6 14-14-8 0-14 5-14 14Z"/><path d="M5 19 19 5"/>',
    }
    paths = icons.get(nome, icons['gem'])
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="display:inline-block;vertical-align:middle">{paths}</svg>'


def _email_wrapper(titulo, corpo_html, preheader=''):
    preheader_html = preheader or titulo
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    @media only screen and (max-width: 620px) {{
      .email-outer {{ padding: 0 !important; }}
      .email-shell {{ width: 100% !important; border-radius: 0 !important; }}
      .email-pad {{ padding-left: 22px !important; padding-right: 22px !important; }}
      .email-title {{ font-size: 28px !important; }}
      .email-btn a {{ display: block !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#F5F2EC;font-family:Montserrat,Arial,sans-serif;color:#6B5E53">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{preheader_html}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#F5F2EC">
    <tr>
      <td class="email-outer" align="center" style="padding:28px 12px">
        <table role="presentation" class="email-shell" width="600" cellspacing="0" cellpadding="0" border="0" style="width:600px;max-width:600px;background:#FFFFFF;border-radius:26px;overflow:hidden;border:1px solid #E8E3D8;box-shadow:0 20px 58px rgba(61,45,32,0.12)">
          <tr>
            <td class="email-pad" bgcolor="#6F7E66" style="padding:34px 38px;background:#6F7E66;background:linear-gradient(135deg,#56634F 0%,#7A866F 58%,#A99668 100%);text-align:center">
              <img src="{EMAIL_LOGO_URL}" width="70" height="70" alt="{EMAIL_BRAND_NAME}" style="display:block;margin:0 auto 14px;border-radius:50%;border:1px solid rgba(255,255,255,0.55);box-shadow:0 10px 28px rgba(38,31,22,0.22)">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto">
                <tr>
                  <td bgcolor="#FFFFFF" style="background:#FFFFFF;border-radius:999px;padding:9px 22px;border:1px solid #E8D6A3;box-shadow:0 8px 22px rgba(38,31,22,0.12)">
                    <span style="display:block;color:#3D2D20;font-family:Georgia,'Times New Roman',serif;font-size:26px;line-height:1;font-weight:700;letter-spacing:-0.02em">{EMAIL_BRAND_NAME}</span>
                  </td>
                </tr>
              </table>
              <p style="margin:10px auto 16px;width:72px;height:1px;background:#E8D6A3;line-height:1px;font-size:1px">&nbsp;</p>
              <h1 class="email-title" style="margin:0;color:#FFFFFF;font-family:Georgia,'Times New Roman',serif;font-size:32px;line-height:1.05;font-weight:700;letter-spacing:-0.03em">{titulo}</h1>
            </td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:34px 38px 30px">{corpo_html}</td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:22px 38px;background:#FBFAF7;border-top:1px solid #E8E3D8;text-align:center">
              <p style="margin:0 0 8px;color:#9E9488;font-size:12px;line-height:1.6">Duvidas sobre seu pedido? Fale com a gente pelo WhatsApp.</p>
              <p style="margin:0;color:#9E9488;font-size:11px;line-height:1.6">© 2026 Barrs Store · <a href="https://www.barrsstore.com.br" style="color:#738269;text-decoration:none">barrsstore.com.br</a></p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _btn(texto, url, cor='#738269'):
    return f'<span class="email-btn"><a href="{url}" style="display:inline-block;padding:14px 28px;background:{cor};color:#fff;border-radius:999px;text-decoration:none;font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;box-shadow:0 10px 22px rgba(83,98,76,0.18)">{texto}</a></span>'


def _email_pedido_resumo(pedido):
    itens_html = ''.join([
        f"""
        <tr>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#3D342C;font-size:14px;line-height:1.35">
            <strong style="font-family:Georgia,'Times New Roman',serif;font-size:15px">{item.nome_produto}</strong>
          </td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#6B5E53;font-size:13px;text-align:center">{item.quantidade}</td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#738269;font-size:14px;font-weight:700;text-align:right">R$ {item.preco_unitario}</td>
        </tr>
        """
        for item in pedido.itens.all()
    ])
    frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Gratis"
    desconto_html = ''
    if pedido.desconto > 0:
        desconto_html = f"""
        <tr>
          <td colspan="2" style="padding-top:10px;color:#9E9488;font-size:13px">Desconto {pedido.cupom_codigo}</td>
          <td style="padding-top:10px;color:#738269;font-size:13px;font-weight:700;text-align:right">- R$ {pedido.desconto}</td>
        </tr>
        """
    return f"""
      <div style="background:#FBFAF7;border:1px solid #E8E3D8;border-radius:18px;padding:20px;margin:24px 0">
        <p style="margin:0 0 14px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Resumo do pedido #{pedido.id}</p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse">
          <tr>
            <th align="left" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Produto</th>
            <th align="center" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Qtd</th>
            <th align="right" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Valor</th>
          </tr>
          {itens_html}
          <tr>
            <td colspan="2" style="padding-top:14px;color:#9E9488;font-size:13px">Subtotal</td>
            <td style="padding-top:14px;color:#6B5E53;font-size:13px;text-align:right">R$ {pedido.subtotal}</td>
          </tr>
          <tr>
            <td colspan="2" style="padding-top:8px;color:#9E9488;font-size:13px">Frete</td>
            <td style="padding-top:8px;color:#6B5E53;font-size:13px;text-align:right">{frete_texto}</td>
          </tr>
          {desconto_html}
          <tr>
            <td colspan="2" style="padding-top:12px;color:#3D2D20;font-size:16px;font-weight:700">Total</td>
            <td style="padding-top:12px;color:#738269;font-size:17px;font-weight:800;text-align:right">R$ {pedido.total}</td>
          </tr>
        </table>
      </div>
    """


def _email_entrega(pedido):
    return f"""
      <div style="background:#F5F2EC;border-radius:16px;padding:18px;margin:20px 0">
        <p style="margin:0 0 10px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Entrega</p>
        <p style="margin:0;color:#6B5E53;font-size:14px;line-height:1.7">
          {pedido.rua}, {pedido.numero}{f" - {pedido.complemento}" if pedido.complemento else ""}<br>
          {pedido.bairro} - {pedido.cidade}/{pedido.estado}<br>
          CEP {pedido.cep}
        </p>
      </div>
    """


def _brevo_payload(destinatario_email, destinatario_nome, assunto, html):
    return {
        'sender': _brevo_sender(),
        'to': [{'email': destinatario_email, 'name': destinatario_nome}],
        'subject': assunto,
        'htmlContent': html,
    }


def enviar_email_confirmacao(pedido):
    """Envia e-mail premium de confirmacao para o cliente via Brevo."""
    try:
        link_acompanhar = site_url(reverse('rastrear_pedido'))
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pagamento foi aprovado e seu pedido ja entrou em preparo com todo o cuidado da Barrs Store.')
            + _email_pedido_resumo(pedido)
            + _email_entrega(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar pedido", link_acompanhar)}</div>'
            + _paragrafo('<span style="color:#9E9488;font-size:13px">Assim que o envio for atualizado, voce recebera o codigo de rastreio automaticamente por e-mail.</span>')
        )
        html = _email_wrapper('Pedido confirmado', corpo, f'Pedido #{pedido.id} confirmado. Total: R$ {pedido.total}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Pedido #{pedido.id} confirmado - Barrs Store', html)
        brevo_admin_email = os.environ.get('BREVO_ADMIN_EMAIL', payload['sender']['email']).strip()
        if brevo_admin_email and brevo_admin_email.lower() != pedido.email.lower():
            payload['bcc'] = [{'email': brevo_admin_email, 'name': EMAIL_BRAND_NAME}]

        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Confirmacao pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='confirmacao')
            logger.warning('E-mail do pedido %s enfileirado para reenvio. erro=%s', pedido.id, erro)
            return False
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail Brevo do pedido %s: %s', pedido.id, exc)
        return False


def enviar_email_pagamento_pendente(pedido):
    """Envia um lembrete premium com link para finalizar o pagamento."""
    if pedido.email_pagamento_pendente_enviado:
        return True
    try:
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pedido foi reservado e esta aguardando a finalizacao do pagamento.')
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Finalizar pagamento", link_pagamento)}</div>'
            + _paragrafo('<span style="color:#9E9488;font-size:13px">Se voce ja pagou, pode ignorar este e-mail. A confirmacao acontece automaticamente assim que o pagamento for aprovado.</span>')
        )
        html = _email_wrapper('Seu pedido foi reservado', corpo, f'Finalize o pagamento do pedido #{pedido.id}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Finalize o pagamento do pedido #{pedido.id} - Barrs Store', html)
        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Pagamento pendente pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if ok:
            pedido.email_pagamento_pendente_enviado = True
            pedido.save(update_fields=['email_pagamento_pendente_enviado'])
            return True
        enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='pagamento_pendente')
        logger.warning('E-mail de pagamento pendente do pedido %s enfileirado. erro=%s', pedido.id, erro)
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de pagamento pendente do pedido %s: %s', pedido.id, exc)
    return False


def enviar_email_rastreio(pedido):
    """Envia o codigo de rastreio ao cliente quando o pedido for enviado."""
    if not pedido.codigo_rastreio:
        return False
    try:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pedido #{pedido.id} ja foi enviado.')
            + f"""
              <div style="background:#FBFAF7;border:1px solid #E8E3D8;border-radius:18px;padding:20px;margin:24px 0">
                <p style="margin:0 0 10px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Rastreio</p>
                <p style="margin:0 0 8px;color:#3D2D20;font-size:16px;font-weight:700">{pedido.codigo_rastreio}</p>
                <p style="margin:0;color:#6B5E53;font-size:14px;line-height:1.6">Transportadora: {transportadora}</p>
              </div>
            """
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar entrega", rastreio_url)}</div>'
            + _paragrafo(f'<span style="color:#9E9488;font-size:13px">Caso o botao nao abra, acesse este link: <a href="{rastreio_url}" style="color:#738269;text-decoration:none">{rastreio_url}</a></span>')
        )
        html = _email_wrapper('Seu pedido foi enviado', corpo, f'Codigo de rastreio do pedido #{pedido.id}: {pedido.codigo_rastreio}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Seu pedido #{pedido.id} foi enviado - Barrs Store', html)
        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Rastreio pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='rastreio')
            logger.warning('E-mail de rastreio do pedido %s enfileirado. erro=%s', pedido.id, erro)
            return False
        pedido.email_rastreio_enviado = True
        pedido.save(update_fields=['email_rastreio_enviado'])
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de rastreio do pedido %s: %s', pedido.id, exc)
        return False


# ── SEQUÊNCIA PÓS-COMPRA PREMIUM ──────────────────────────────────

def enviar_email_poscompra_1(pedido):
    """E-mail 1 (≈1h após confirmação): pedido em preparo."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    corpo = (
        f'<div style="text-align:center;margin:0 0 18px">{_email_icon("gem", 30)}</div>'
        + _paragrafo(f'Oi, <strong>{pedido.nome.split()[0]}</strong>! Que alegria receber seu pedido.')
        + _paragrafo('Já estamos separando cada peça com muito cuidado para garantir que chegue até você perfeita. A Barrs Store cuida de cada detalhe — da embalagem à entrega.')
        + _paragrafo(f'<strong>Pedido #{pedido.id}</strong> · Total: <strong style="color:#8A947C">R$ {pedido.total}</strong>')
        + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar meu pedido", link_rastrear)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Em breve você receberá o código de rastreio. Se tiver qualquer dúvida, estamos no WhatsApp.</span>')
    )
    html = _email_wrapper('Seu pedido está em boas mãos', corpo)
    ok = _brevo_send(f'Seu pedido #{pedido.id} está sendo preparado — Barrs Store', html, pedido.email, pedido.nome)
    if ok:
        pedido.email_poscompra_1_enviado = True
        pedido.save(update_fields=['email_poscompra_1_enviado'])
    return ok


def enviar_email_poscompra_2(pedido):
    """E-mail 2 (≈24h após confirmação): bastidores da marca."""
    link_loja = site_url('/')
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, enquanto preparamos seu pedido com todo o carinho, queríamos te contar um pouquinho sobre como trabalhamos por aqui.')
        + _paragrafo('Cada peça da Barrs Store passa por uma curadoria criteriosa. Acreditamos que um acessório bem escolhido não é apenas um adorno — é uma extensão da sua personalidade.')
        + '<div style="background:#F5F2EC;border-radius:10px;padding:20px;margin:20px 0">'
        + '<p style="font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">DICA DE CUIDADO</p>'
        + _paragrafo('Guarde suas peças em local seco, longe de perfumes e produtos químicos. Para anéis e pulseiras, evite contato com água. Assim, elas duram muito mais.')
        + '</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Ver novidades na loja", link_loja)}</div>'
    )
    html = _email_wrapper('O cuidado que vai junto com cada peça', corpo)
    ok = _brevo_send(f'Um cuidado especial sobre seu pedido #{pedido.id} — Barrs Store', html, pedido.email, pedido.nome)
    if ok:
        pedido.email_poscompra_2_enviado = True
        pedido.save(update_fields=['email_poscompra_2_enviado'])
    return ok


def enviar_email_poscompra_3(pedido):
    """E-mail 3 (≈3 dias): atualização de envio / rastreio."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    if pedido.codigo_rastreio:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        trecho_rastreio = (
            '<div style="background:#E8EDE3;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center">'
            + f'<p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#8A947C;margin:0 0 6px">CÓDIGO DE RASTREIO</p>'
            + f'<p style="font-size:18px;font-weight:700;color:#3d2d20;margin:0;letter-spacing:1px">{pedido.codigo_rastreio}</p>'
            + f'<p style="font-size:12px;color:#9E9488;margin:6px 0 0">{transportadora}</p>'
            + '</div>'
            + f'<div style="text-align:center;margin:20px 0">{_btn("Rastrear minha encomenda", rastreio_url)}</div>'
        )
        subtitulo = 'Seu pedido saiu para entrega'
        intro = _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, uma ótima notícia! Seu pedido #{pedido.id} foi enviado e já está a caminho.')
    else:
        trecho_rastreio = (
            _paragrafo('Estamos finalizando o preparo do seu pedido e em breve ele sairá para entrega. Você receberá o código de rastreio assim que for despachado.')
            + f'<div style="text-align:center;margin:24px 0">{_btn("Rastrear pedido", link_rastrear)}</div>'
        )
        subtitulo = 'Seu pedido está quase pronto'
        intro = _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, o pedido #{pedido.id} está nos últimos detalhes de preparo!')

    corpo = intro + trecho_rastreio + _paragrafo('<span style="color:#9E9488;font-size:13px">Qualquer dúvida, estamos no WhatsApp. Mal podemos esperar para você receber suas peças.</span>')
    html = _email_wrapper(subtitulo, corpo)
    ok = _brevo_send(f'Atualização do seu pedido #{pedido.id} — Barrs Store', html, pedido.email, pedido.nome)
    if ok:
        pedido.email_poscompra_3_enviado = True
        pedido.save(update_fields=['email_poscompra_3_enviado'])
    return ok


def enviar_email_poscompra_4(pedido):
    """E-mail 4 (≈7 dias): pós-entrega estimada, verificação."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    link_wa = 'https://wa.me/5511913225256'
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, já faz alguns dias desde que enviamos seu pedido. Chegou tudo certinho?')
        + _paragrafo('Adoraríamos saber como está sendo a experiência com suas novas peças. Se tiver qualquer dúvida sobre a entrega, estamos aqui para resolver com agilidade.')
        + '<div style="display:flex;gap:12px;margin:24px 0;justify-content:center;flex-wrap:wrap">'
        + f'<a href="{link_wa}" style="display:inline-block;padding:12px 24px;background:#25d366;color:#fff;border-radius:999px;text-decoration:none;font-size:13px;font-weight:700">{_email_icon("message", 16, "#ffffff")} <span style="vertical-align:middle">Falar no WhatsApp</span></a>'
        + f'<a href="{link_rastrear}" style="display:inline-block;padding:12px 24px;background:#F5F2EC;color:#6B5E53;border:1px solid #D9D3C7;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">Rastrear pedido</a>'
        + '</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Sua satisfação é o que nos move a continuar criando peças exclusivas com tanto cuidado.</span>')
    )
    html = _email_wrapper('Chegou tudo bem?', corpo)
    ok = _brevo_send(f'Tudo certo com seu pedido #{pedido.id}, {pedido.nome.split()[0]}? — Barrs Store', html, pedido.email, pedido.nome)
    if ok:
        pedido.email_poscompra_4_enviado = True
        pedido.save(update_fields=['email_poscompra_4_enviado'])
    return ok


def enviar_email_poscompra_5(pedido):
    """E-mail 5 (≈15 dias): fidelização e retorno à loja."""
    link_loja = site_url('/')
    link_wa = 'https://wa.me/5511913225256'
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, obrigada de verdade por escolher a Barrs Store.')
        + _paragrafo('Clientes como você são a razão de cada detalhe que dedicamos às nossas peças — da curadoria à embalagem. Você é especial para a gente.')
        + '<div style="background:#F5F2EC;border-radius:10px;padding:20px;margin:20px 0;text-align:center">'
        + f'<div style="margin:0 0 10px">{_email_icon("leaf", 22)}</div>'
        + '<p style="font-size:13px;font-weight:600;color:#3d2d20;margin:0 0 8px">Novidades chegando todo mês</p>'
        + _paragrafo('<span style="font-size:13px;color:#9E9488">Acompanhe nossas novidades no Instagram e seja a primeira a saber dos lançamentos exclusivos.</span>')
        + f'<a href="https://www.instagram.com/barrsstore" style="display:inline-block;margin-top:8px;padding:10px 22px;background:#8A947C;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">@barrsstore no Instagram</a>'
        + '</div>'
        + f'<div style="text-align:center;margin:20px 0">{_btn("Ver novas peças na loja", link_loja)}</div>'
        + _paragrafo(f'<span style="color:#9E9488;font-size:13px">Tem alguma peça dos sonhos? Me conta pelo <a href="{link_wa}" style="color:#8A947C">WhatsApp</a> — amo ajudar.</span>')
    )
    html = _email_wrapper('Uma mensagem especial para você', corpo)
    ok = _brevo_send(f'Obrigada, {pedido.nome.split()[0]} — Barrs Store', html, pedido.email, pedido.nome)
    if ok:
        pedido.email_poscompra_5_enviado = True
        pedido.save(update_fields=['email_poscompra_5_enviado'])
    return ok


# ── SEQUÊNCIA ABANDONO DE CARRINHO PREMIUM ─────────────────────────

def enviar_email_abandono_1(carrinho):
    """E-mail 1 (≈1h): primeiro contato suave."""
    if not carrinho.email_cliente:
        return False
    link_checkout = carrinho.link_checkout()
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False

    itens_html = ''.join([
        f'<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #E8EDE3">'
        + (f'<img src="{item.produto.imagem.url}" alt="{item.produto.nome}" style="width:52px;height:52px;border-radius:8px;object-fit:cover;background:#E8EDE3;flex-shrink:0">'
           if item.produto.imagem else
           f'<div style="width:52px;height:52px;border-radius:8px;background:#E8EDE3;display:flex;align-items:center;justify-content:center;flex-shrink:0">{_email_icon("gem", 22)}</div>')
        + f'<div style="flex:1"><p style="font-size:13px;font-weight:600;color:#3d2d20;margin:0">{item.produto.nome}</p>'
        + (f'<p style="font-size:11px;color:#8A947C;margin:2px 0 0">Tamanho: {item.tamanho}</p>' if item.tamanho else '')
        + f'</div><p style="font-size:14px;font-weight:600;color:#8A947C;flex-shrink:0">R$ {item.subtotal()}</p></div>'
        for item in itens
    ])

    corpo = (
        _paragrafo('Você deixou algumas peças especiais no carrinho.')
        + _paragrafo('Não queremos que essas peças fiquem esperando sem você. Seu carrinho ainda está salvo, exatamente como você deixou.')
        + f'<div style="background:#F5F2EC;border-radius:10px;padding:16px 20px;margin:20px 0">{itens_html}</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Finalizar minha compra", link_checkout)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Com dúvida sobre tamanho ou entrega? Estamos no WhatsApp, é só chamar.</span>')
    )
    html = _email_wrapper('Você esqueceu algo especial', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Seu carrinho ainda está aqui — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_1_enviado = True
        carrinho.save(update_fields=['email_abandono_1_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_2(carrinho):
    """E-mail 2 (≈24h): destaca benefícios e produtos."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()
    total = carrinho.total()

    corpo = (
        _paragrafo('Suas peças ainda estão esperando por você.')
        + _paragrafo('Percebemos que algumas peças ficaram no seu carrinho. Elas combinam muito com você.')
        + '<div style="background:#E8EDE3;border-radius:10px;padding:16px 20px;margin:20px 0">'
        + '<p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#8A947C;margin:0 0 10px">POR QUE COMPRAR NA BARRS STORE</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 8px;line-height:1.6">{_email_icon("truck", 15)} &nbsp;Entrega para todo o Brasil</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 8px;line-height:1.6">{_email_icon("gem", 15)} &nbsp;Semijoias com acabamento premium</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0;line-height:1.6">{_email_icon("message", 15)} &nbsp;Atendimento humanizado via WhatsApp</p>'
        + '</div>'
        + f'<p style="font-size:15px;font-weight:600;color:#3d2d20;margin:16px 0">Total do carrinho: <span style="color:#8A947C">R$ {total}</span></p>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Garantir meu pedido agora", link_checkout)}</div>'
    )
    html = _email_wrapper('Suas peças estão esperando por você', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Ainda dá tempo — seu carrinho está salvo — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_2_enviado = True
        carrinho.save(update_fields=['email_abandono_2_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_3(carrinho):
    """E-mail 3 (≈48h): urgência suave, última mensagem."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()

    corpo = (
        _paragrafo('Esta é nossa última mensagem sobre seu carrinho — prometemos.')
        + _paragrafo('Só queríamos lembrar que os estoques da Barrs Store são limitados. Não queremos que você perca as peças que escolheu com tanto cuidado.')
        + '<div style="background:#F5F2EC;border:1px solid #D9D3C7;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center">'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 4px">Você tem <strong>{sum(i.quantidade for i in itens)} peça(s)</strong> reservada(s)</p>'
        + f'<p style="font-size:18px;font-weight:700;color:#8A947C;margin:0">R$ {carrinho.total()}</p>'
        + '</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Finalizar antes que esgote", link_checkout)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:12px">Se mudou de ideia, sem problema — não vamos te incomodar mais. Mas se precisar de nós, estamos sempre no WhatsApp.</span>')
    )
    html = _email_wrapper('Última chance para seu carrinho', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Não deixe escapar — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_3_enviado = True
        carrinho.save(update_fields=['email_abandono_3_enviado', 'atualizado_em'])
    return ok


# ── WHATSAPP: NOTIFICAÇÃO DE NOVO PEDIDO ──────────────────────────
def enviar_whatsapp_pedido(pedido):
    """Envia notificação no WhatsApp quando chegar um novo pedido."""
    try:
        painel_url = site_url(f'/painel/loja/pedido/{pedido.id}/change/')
        mensagem = (
            f"Novo pedido #{pedido.id}\n\n"
            f"Total: R$ {pedido.total}\n"
            f"Status: {pedido.get_status_display()}\n"
            f"Ver no painel: {painel_url}"
        )

        whatsapp_phone = os.environ.get('WHATSAPP_ADMIN_PHONE', '5511913225256').strip()
        callmebot_key = os.environ.get('CALLMEBOT_API_KEY', '').strip()
        if not callmebot_key:
            logger.warning('CALLMEBOT_API_KEY nao configurada. WhatsApp do pedido %s nao foi enviado.', pedido.id)
            return

        http_requests.get(
            'https://api.callmebot.com/whatsapp.php',
            params={
                'phone': whatsapp_phone,
                'text': mensagem,
                'apikey': callmebot_key,
            },
            timeout=10,
        )
    except Exception:
        pass  # Nunca quebra o pedido se o WhatsApp falhar


# ── HELPER: dados do carrinho para navbar ──────────────────────────
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


# ── HOME ───────────────────────────────────────────────────────────
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

    logger.info('[LEAD] Nome e telefone capturados para atendimento via WhatsApp.')
    return JsonResponse({'ok': True, 'nome': nome, 'telefone': telefone})


def home(request):
    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')
    categoria_slug = request.GET.get('categoria', '')

    produtos = Produto.objects.filter(visivel=True)

    if busca:
        produtos = produtos.filter(
            Q(nome__icontains=busca) | Q(descricao__icontains=busca)
        )

    if categoria_slug:
        produtos = produtos.filter(categoria__slug=categoria_slug)

    if ordem == 'menor':
        produtos = produtos.order_by('preco')
    elif ordem == 'maior':
        produtos = produtos.order_by('-preco')
    elif ordem == 'nome':
        produtos = produtos.order_by('nome')
    else:
        produtos = produtos.order_by('-criado_em')

    total_produtos = produtos.count()
    try:
        page_number = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page_number = 1
    per_page = 12
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_params.pop('partial', None)
    base_query = query_params.urlencode()

    # Resposta parcial usada pelo infinite scroll do front: devolve so o chunk daquela pagina.
    is_partial = (
        request.GET.get('partial') == '1'
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    )
    if is_partial:
        from django.template.loader import render_to_string
        inicio = (page_number - 1) * per_page
        fim = page_number * per_page
        chunk = list(produtos[inicio:fim])
        html = render_to_string('partials/product_cards_chunk.html', {'produtos': chunk}, request=request)
        return JsonResponse({
            'html': html,
            'has_next': total_produtos > fim,
            'next_page': page_number + 1 if total_produtos > fim else 0,
        })

    produtos_pagina = produtos[:page_number * per_page]
    has_next_page = total_produtos > page_number * per_page
    next_page_url = ''
    if has_next_page:
        next_query = query_params.copy()
        next_query['page'] = page_number + 1
        next_page_url = f'?{next_query.urlencode()}#produtos'

    categorias = Categoria.objects.all()
    seo = seo_context(
        request,
        'Barrs Store - Acessorios modernos e exclusivos',
        'Compre acessorios femininos modernos na Barrs Store: aneis, brincos, colares e pulseiras com envio para todo o Brasil.',
        robots='noindex, follow' if request.GET else 'index, follow',
    )

    context = {
        'produtos': produtos_pagina,
        'has_next_page': has_next_page,
        'next_page_url': next_page_url,
        'next_page_number': page_number + 1 if has_next_page else 0,
        'base_query': base_query,
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': total_produtos,
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
    }
    context.update(seo)
    return render(request, 'home.html', context)


# ── DETALHE DO PRODUTO ─────────────────────────────────────────────
def detalhe_produto(request, slug):
    produto = get_object_or_404(Produto, slug=slug, visivel=True)
    if not request.user.is_staff:
        Produto.objects.filter(pk=produto.pk).update(cliques=F('cliques') + 1)
    relacionados = Produto.objects.filter(visivel=True, estoque__gt=0, categoria=produto.categoria).exclude(id=produto.id)[:4]
    if not relacionados:
        relacionados = Produto.objects.filter(visivel=True, estoque__gt=0).exclude(id=produto.id)[:4]
    image_url = produto.imagem.url if produto.imagem else ''
    seo = seo_context(
        request,
        f'{produto.nome} - Barrs Store',
        produto.seo_description(),
        image_url=image_url,
    )
    context = {
        'produto': produto,
        'relacionados': relacionados,
        'qtd_carrinho': get_carrinho_info(request),
        'preco_schema': str(produto.preco).replace(',', '.'),
    }
    context.update(seo)
    return render(request, 'detalhe.html', context)


def detalhe_produto_id(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id, visivel=True)
    return redirect(produto.get_absolute_url(), permanent=True)


# ── CARRINHO ───────────────────────────────────────────────────────
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


# ── CALCULAR FRETE VIA MELHOR ENVIO ───────────────────────────────
@ratelimit(key='ip', rate='30/m', method='GET', block=True)
def calcular_frete_melhor_envio(request):
    """Calcula frete real via API do Melhor Envio pelo CEP."""
    cep_destino = request.GET.get('cep', '').replace('-', '').replace(' ', '')
    
    if len(cep_destino) != 8:
        return JsonResponse({'erro': 'CEP inválido'}, status=400)
    
    token = os.environ.get('MELHOR_ENVIO_TOKEN', '').strip()
    if not token:
        return JsonResponse({'erro': 'Frete indisponível no momento.'}, status=503)
    
    try:
        carrinho = None
        carrinho_id = request.session.get('carrinho_id')
        if carrinho_id:
            try:
                carrinho = Carrinho.objects.prefetch_related('itens__produto').get(id=carrinho_id)
            except Carrinho.DoesNotExist:
                request.session.pop('carrinho_id', None)

        produtos_cotacao = []
        subtotal_declarado = Decimal('1.00')
        pacote = pacote_envio_por_quantidade(1)
        if carrinho:
            subtotal_declarado = max(carrinho.total(), Decimal('1.00'))
            total_itens = sum(item.quantidade for item in carrinho.itens.all())
            pacote = pacote_envio_por_quantidade(total_itens)
            # A cotacao do Melhor Envio usa produtos com dimensoes e valor segurado.
            # Como a loja envia tudo em uma caixa padrao, cotamos um volume unico.
            produtos_cotacao = [{
                'id': f'carrinho-{carrinho.id}',
                'width': pacote['width'],
                'height': pacote['height'],
                'length': pacote['length'],
                'weight': pacote['weight'],
                'insurance_value': float(subtotal_declarado),
                'quantity': 1,
            }]

        payload = {
            'from': {'postal_code': apenas_digitos(os.environ.get('ME_REMETENTE_CEP', '08275700'))},
            'to': {'postal_code': cep_destino},
            'package': {
                'height': pacote['height'],
                'width': pacote['width'],
                'length': pacote['length'],
                'weight': pacote['weight'],
            },
            'options': {
                # Mantem o calculo do carrinho igual ao envio criado depois da compra.
                'insurance_value': float(subtotal_declarado),
                'receipt': False,
                'own_hand': False,
                'reverse': False,
                'non_commercial': True,
            },
        }
        if produtos_cotacao:
            payload['products'] = produtos_cotacao

        # Se quiser limitar manualmente no Railway, use MELHOR_ENVIO_SERVICES.
        # Sem essa variavel, o Melhor Envio retorna Correios, Loggi e outras opcoes disponiveis para o CEP.
        servicos_configurados = os.environ.get('MELHOR_ENVIO_SERVICES', '').strip()
        if servicos_configurados:
            payload['services'] = servicos_configurados

        res = http_requests.post(
            f'{melhor_envio_base_url()}/api/v2/me/shipment/calculate',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'BarrsStore contato.barrsstore@gmail.com',
            },
            json=payload,
            timeout=10,
        )
        
        data = res.json()
        if res.status_code >= 400 or not isinstance(data, list):
            return JsonResponse({'erro': 'Não foi possível calcular o frete agora.'}, status=502)
        opcoes = []
        
        opcoes_permitidas = {
            ('CORREIOS', 'PAC'),
            ('CORREIOS', 'SEDEX'),
            ('LOGGI', 'EXPRESS'),
        }

        for servico in data:
            empresa = servico.get('company', {}).get('name', '')
            nome = servico.get('name', '')
            chave = (empresa.upper(), nome.upper())
            if chave not in opcoes_permitidas:
                continue

            if 'error' not in servico and servico.get('price'):
                opcoes.append({
                    'id': servico.get('id'),
                    'nome': nome,
                    'empresa': empresa,
                    'preco': float(servico.get('price', 0)),
                    'prazo': servico.get('delivery_time', ''),
                })
        
        opcoes.sort(key=lambda x: x['preco'])
        return JsonResponse({'opcoes': opcoes})
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# ── ADICIONAR AO CARRINHO ──────────────────────────────────────────
@require_POST
@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def adicionar_carrinho(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    if not produto.visivel or produto.estoque <= 0:
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

    next_url = request.POST.get('next', 'carrinho')
    if next_url == 'detalhe':
        url = produto.get_absolute_url() + '?added=1'
        return redirect(url)
    if next_url == 'home':
        return redirect('home')
    return redirect('carrinho')


# ── REMOVER 1 UNIDADE ──────────────────────────────────────────────
@require_POST
def remover_item(request, item_id):
    item = get_object_or_404(ItemCarrinho, id=item_id)
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
    item = get_object_or_404(ItemCarrinho, id=item_id)
    carrinho = item.carrinho
    item.delete()
    carrinho.save(update_fields=['atualizado_em'])
    return redirect('carrinho')


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

    valido, motivo = cupom.valido_para(subtotal)
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
    itens = carrinho.itens.all()

    if not itens:
        return redirect('carrinho')

    def render_checkout(perfil=None):
        frete_valor = request.POST.get('frete_valor') or request.GET.get('frete_valor', '')
        frete_nome = request.POST.get('frete_nome') or request.GET.get('frete_nome', '')
        frete_service_id = request.POST.get('frete_service_id') or request.GET.get('frete_service_id', '')
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
        }
        context.update(noindex_context(request, 'Checkout - Barrs Store'))
        return render(request, 'checkout.html', context)

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            return render_checkout()

        cliente = request.user if request.user.is_authenticated else None
        salvar_lead_na_sessao(
            request,
            request.POST.get('nome', ''),
            request.POST.get('telefone', ''),
        )
        aplicar_lead_no_carrinho(request, carrinho)

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
                return render_checkout()

        cpf_pedido = apenas_digitos(request.POST.get('cpf', ''))
        if len(cpf_pedido) != 11:
            messages.error(request, 'Informe um CPF valido com 11 numeros.')
            return render_checkout()
        if not cpf_valido(cpf_pedido):
            messages.error(request, 'Informe um CPF valido.')
            return render_checkout()

        for item in itens.select_related('produto'):
            if not item.produto or not item.produto.visivel or item.produto.estoque < item.quantidade:
                messages.error(request, f'O produto {item.produto.nome if item.produto else item.nome_produto} nao tem estoque suficiente.')
                return redirect('carrinho')
            if item.tamanho:
                tamanho = TamanhoAnel.objects.filter(produto=item.produto, numero=item.tamanho).first()
                if not tamanho or tamanho.estoque < item.quantidade:
                    messages.error(request, f'O tamanho {item.tamanho} de {item.produto.nome} nao tem estoque suficiente.')
                    return redirect('carrinho')

        if not request.user.is_authenticated:
            email_pedido = request.POST.get('email', '').strip().lower()
            senha = request.POST.get('senha', '').strip()

            if not senha:
                messages.error(request, 'Digite sua senha para entrar ou criar sua conta antes de finalizar.')
                return render_checkout()

            usuario_existente = User.objects.filter(email__iexact=email_pedido).first()
            if usuario_existente:
                user = authenticate(request, username=usuario_existente.username, password=senha)
                if not user:
                    messages.error(request, 'Nao foi possivel validar suas credenciais. Confira os dados e tente novamente.')
                    return render_checkout()
                login(request, user)
                cliente = user
            else:
                nome_completo = request.POST.get('nome', '').strip()
                partes = nome_completo.split()
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
                    return render_checkout()
                user = User.objects.create_user(
                    username=email_pedido,
                    email=email_pedido,
                    password=senha,
                    first_name=partes[0] if partes else '',
                    last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
                )
                login(request, user)
                cliente = user

            perfil, _ = PerfilCliente.objects.get_or_create(user=cliente)
            perfil.telefone = request.POST.get('telefone', '').strip()
            perfil.cep = request.POST.get('cep', '').strip()
            perfil.rua = request.POST.get('rua', '').strip()
            perfil.numero = request.POST.get('numero', '').strip()
            perfil.complemento = request.POST.get('complemento', '').strip()
            perfil.bairro = request.POST.get('bairro', '').strip()
            perfil.cidade = request.POST.get('cidade', '').strip()
            perfil.estado = request.POST.get('estado', '').strip()
            perfil.save()

        estado_pedido = request.POST.get('estado', 'SP')
        subtotal = carrinho.total()
        # Frete deve vir da opção escolhida pelo comprador no Melhor Envio.
        frete_selecionado = request.POST.get('frete_valor', '').replace(',', '.').strip()
        if not frete_selecionado:
            messages.error(request, 'Calcule e selecione uma opção de frete no carrinho antes de finalizar.')
            return render_checkout()
        try:
            frete = Decimal(frete_selecionado)
            if frete < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            messages.error(request, 'Não foi possível validar o frete selecionado. Calcule o frete novamente no carrinho.')
            return render_checkout()

        desconto = Decimal('0')
        cupom_codigo = request.POST.get('cupom_codigo', '').strip().upper()
        cupom = None
        if cupom_codigo:
            cupom = Cupom.objects.filter(codigo__iexact=cupom_codigo).first()
            if not cupom:
                messages.error(request, 'Cupom nao encontrado.')
                return render_checkout()
            valido, motivo = cupom.valido_para(subtotal)
            if not valido:
                messages.error(request, motivo)
                return render_checkout()
            desconto = cupom.calcular_desconto(subtotal, frete)

        total = subtotal - desconto + frete
        try:
            frete_service_id = int(request.POST.get('frete_service_id') or 0) or None
        except (TypeError, ValueError):
            frete_service_id = None

        pedido = Pedido.objects.create(
            cliente=cliente,
            nome=request.POST['nome'],
            email=request.POST['email'],
            telefone=request.POST.get('telefone', ''),
            cpf=cpf_pedido,
            cep=request.POST['cep'],
            rua=request.POST['rua'],
            numero=request.POST['numero'],
            complemento=request.POST.get('complemento', ''),
            bairro=request.POST['bairro'],
            cidade=request.POST['cidade'],
            estado=estado_pedido,
            forma_pagamento='pix',
            subtotal=subtotal,
            desconto=desconto,
            cupom_codigo=cupom.codigo.upper() if cupom else '',
            frete=frete,
            total=total,
            melhor_envio_service_id=frete_service_id,
        )

        for item in itens:
            ItemPedido.objects.create(
                pedido=pedido,
                produto=item.produto,
                nome_produto=item.produto.nome,
                quantidade=item.quantidade,
                preco_unitario=item.produto.preco,
                tamanho=item.tamanho,
            )

        # Salva email no carrinho antes de deletar (para possível recuperação futura)
        carrinho.email_cliente = request.POST.get('email', '').strip().lower()
        carrinho.save(update_fields=['email_cliente'])
        carrinho.delete()
        del request.session['carrinho_id']

        # Notificacao interna de novo pedido pendente.
        logger.info('[CHECKOUT] Pedido %s criado. Aguardando pagamento.', pedido.id)
        enviar_whatsapp_pedido(pedido)
        enviar_email_pagamento_pendente(pedido)

        return redirect('confirmacao', pedido_id=pedido.id, token=pedido.access_token)

    perfil = None
    if request.user.is_authenticated:
        perfil, _ = PerfilCliente.objects.get_or_create(user=request.user)

    return render_checkout(perfil)


# ── CONFIRMAÇÃO ────────────────────────────────────────────────────
def confirmacao(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    if pedido.status == 'confirmado':
        return redirect('pagamento_sucesso', pedido_id=pedido.id, token=pedido.access_token)
    context = {
        'pedido': pedido,
        'mp_public_key': settings.MERCADOPAGO_PUBLIC_KEY,
    }
    context.update(noindex_context(request, f'Pedido #{pedido.id} - Barrs Store'))
    return render(request, 'confirmacao.html', context)


# ── MERCADO PAGO: CRIAR PREFERÊNCIA ───────────────────────────────
@require_POST
@ratelimit(key='ip', rate='15/m', method='POST', block=True)
def criar_preferencia(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        return JsonResponse({'erro': 'Mercado Pago nao configurado.'}, status=503)
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

    items = []
    if pedido.desconto > 0:
        items.append({
            "title": f"Pedido #{pedido.id} - Barrs Store",
            "quantity": 1,
            "unit_price": float(pedido.total),
            "currency_id": "BRL",
        })
    else:
        for item in pedido.itens.all():
            items.append({
                "title": item.nome_produto,
                "quantity": int(item.quantidade),
                "unit_price": float(item.preco_unitario),
                "currency_id": "BRL",
            })

        # Adiciona frete como item separado se houver
        if pedido.frete > 0:
            items.append({
                "title": "Frete",
                "quantity": 1,
                "unit_price": float(pedido.frete),
                "currency_id": "BRL",
            })

    # Limpa telefone — MP só aceita números
    payer = dados_pagador_mercadopago(pedido)

    preference_data = {
        "items": items,
        "payer": payer,
        "back_urls": {
            "success": site_url(reverse('pagamento_sucesso', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
            "failure": site_url(reverse('pagamento_falha', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
            "pending": site_url(reverse('pagamento_pendente', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
        },
        "auto_return": "approved",
        "notification_url": site_url(reverse('webhook_mp')),
        "external_reference": str(pedido.id),
        "metadata": {
            "pedido_id": pedido.id,
        },
        "statement_descriptor": "BARRS STORE",
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response.get("response", {})
    if preference_response.get("status", 500) >= 400 or "id" not in preference:
        logger.warning(
            'Falha ao criar preferencia Mercado Pago do pedido %s. Status %s: %s',
            pedido.id,
            preference_response.get("status"),
            preference,
        )
        return JsonResponse({'erro': 'Nao foi possivel iniciar o pagamento.'}, status=502)

    return JsonResponse({
        "preference_id": preference["id"],
        "init_point": preference["init_point"],
    })


@require_POST
@ratelimit(key='ip', rate='12/m', method='POST', block=True)
def processar_pagamento_brick(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    if pedido.status == 'confirmado':
        return JsonResponse({
            'status': 'approved',
            'pedido_status': pedido.status,
            'redirect_url': reverse('pagamento_sucesso', kwargs={
                'pedido_id': pedido.id,
                'token': pedido.access_token,
            }),
        })
    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        return JsonResponse({'erro': 'Mercado Pago nao configurado.'}, status=503)

    try:
        form_data = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'erro': 'Dados de pagamento invalidos.'}, status=400)

    payer_front = form_data.get('payer') or {}
    payer = dados_pagador_mercadopago(pedido)
    # A API de pagamento direto do Brick rejeita payer.name; usa first_name/last_name.
    payer.pop('name', None)
    # Sempre usa o email do pedido (token UUID ja garante autoria); ignora o que vier do front.
    if not payer.get('identification') and isinstance(payer_front.get('identification'), dict):
        payer['identification'] = payer_front['identification']

    payment_data = {
        'transaction_amount': float(pedido.total),
        'description': f'Pedido #{pedido.id} - Barrs Store',
        'payment_method_id': form_data.get('payment_method_id'),
        'payer': payer,
        'external_reference': str(pedido.id),
        'notification_url': site_url(reverse('webhook_mp')),
        'metadata': {
            'pedido_id': pedido.id,
        },
        'statement_descriptor': 'BARRS STORE',
    }

    # Cartao usa token/parcelas/emissor. Pix nao precisa desses campos.
    if form_data.get('token'):
        payment_data['token'] = form_data.get('token')
    if form_data.get('installments'):
        try:
            payment_data['installments'] = int(form_data.get('installments'))
        except (TypeError, ValueError):
            payment_data['installments'] = 1
    elif form_data.get('token'):
        payment_data['installments'] = 1
    if form_data.get('issuer_id'):
        try:
            payment_data['issuer_id'] = int(form_data.get('issuer_id'))
        except (TypeError, ValueError):
            payment_data['issuer_id'] = form_data.get('issuer_id')

    if not payment_data.get('payment_method_id'):
        logger.warning('[MP-BRICK] Metodo de pagamento ausente no pedido %s.', pedido.id)
        return JsonResponse({'erro': 'Selecione uma forma de pagamento.'}, status=400)

    logger.info(
        '[MP-BRICK] Criando pagamento pedido=%s metodo=%s total=%s',
        pedido.id,
        payment_data.get('payment_method_id'),
        pedido.total,
    )
    logger.info(
        '[MP-BRICK] Payload seguro pedido=%s: %s',
        pedido.id,
        payload_pagamento_seguro_para_log(payment_data),
    )
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    request_options = mercadopago.config.RequestOptions()
    request_options.custom_headers = {
        'X-Idempotency-Key': str(uuid.uuid4()),
    }
    payment_response = sdk.payment().create(payment_data, request_options)
    payment = payment_response.get('response', {})
    status_code = payment_response.get('status', 500)

    if status_code >= 400:
        logger.warning(
            '[MP-BRICK] Falha ao criar pagamento pedido=%s status=%s resposta=%s',
            pedido.id,
            status_code,
            resumir_erro_mercadopago(payment),
        )
        logger.warning(
            '[MP-BRICK] Payload que falhou pedido=%s: %s',
            pedido.id,
            payload_pagamento_seguro_para_log(payment_data),
        )
        return JsonResponse({
            'erro': payment.get('message') or 'Pagamento nao aprovado. Confira os dados e tente novamente.',
            'detalhe': payment.get('status_detail', ''),
        }, status=400)

    payment_id = payment.get('id')
    status = payment.get('status')
    status_detail = payment.get('status_detail')
    logger.info(
        '[MP-BRICK] Pagamento criado pedido=%s payment_id=%s status=%s detail=%s',
        pedido.id,
        payment_id,
        status,
        status_detail,
    )

    if payment_id:
        confirmar_pagamento_mercadopago(payment_id, pedido_id_fallback=str(pedido.id))
        pedido.refresh_from_db()

    if status == 'approved' or pedido.status == 'confirmado':
        redirect_url = reverse('pagamento_sucesso', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})
    elif status in ('pending', 'in_process'):
        redirect_url = reverse('pagamento_pendente', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})
    else:
        redirect_url = reverse('pagamento_falha', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})

    return JsonResponse({
        'id': payment_id,
        'status': status,
        'status_detail': status_detail,
        'pedido_status': pedido.status,
        'redirect_url': redirect_url,
        'point_of_interaction': payment.get('point_of_interaction') or {},
    })


# ── MERCADO PAGO: RETORNOS ─────────────────────────────────────────
@ratelimit(key='ip', rate='30/m', method='GET', block=False)
def pagamento_sucesso(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id and pedido.status != 'confirmado':
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento - Barrs Store'))
    return render(request, 'pagamento_sucesso.html', context)


@ratelimit(key='ip', rate='30/m', method='GET', block=False)
def pagamento_falha(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento nao aprovado - Barrs Store'))
    return render(request, 'pagamento_falha.html', context)


@ratelimit(key='ip', rate='30/m', method='GET', block=False)
def pagamento_pendente(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id:
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento pendente - Barrs Store'))
    return render(request, 'pagamento_pendente.html', context)


@ratelimit(key='ip', rate='120/m', method='GET', block=False)
def status_pagamento(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    return JsonResponse({
        'status': pedido.status,
        'confirmado': pedido.status == 'confirmado',
        'sucesso_url': reverse('pagamento_sucesso', kwargs={
            'pedido_id': pedido.id,
            'token': pedido.access_token,
        }),
    })


# ── MERCADO PAGO: WEBHOOK ──────────────────────────────────────────
@csrf_exempt
@require_POST
def webhook_mercadopago(request):
    data = {}
    try:
        if request.body:
            data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    assinatura_ok, motivo_assinatura = validar_assinatura_mercadopago(request, data)
    if not assinatura_ok:
        logger.warning('[MP] Webhook com assinatura nao validada: %s', motivo_assinatura)
        if getattr(settings, 'MERCADOPAGO_WEBHOOK_STRICT', False):
            return JsonResponse({"status": "forbidden"}, status=403)

    notification_type = data.get("type") or data.get("topic") or request.GET.get("type") or request.GET.get("topic")
    payment_id = (
        data.get("data", {}).get("id")
        or data.get("id")
        or request.GET.get("data.id")
        or request.GET.get("id")
    )

    logger.info('[MP] Webhook recebido: type=%s payment_id=%s', notification_type, payment_id)

    if notification_type == "payment" and payment_id:
        confirmar_pagamento_mercadopago(payment_id)
    elif notification_type == "merchant_order" and payment_id:
        confirmar_merchant_order_mercadopago(payment_id)

    return JsonResponse({"status": "ok"})


# ── CADASTRO ───────────────────────────────────────────────────────
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def cadastro(request):
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            context = {'qtd_carrinho': get_carrinho_info(request)}
            context.update(noindex_context(request, 'Criar conta - Barrs Store'))
            return render(request, 'cadastro.html', context)

        nome = request.POST.get('nome', '').strip()
        email = request.POST.get('email', '').strip()
        senha = request.POST.get('senha', '')
        senha2 = request.POST.get('senha2', '')

        if senha != senha2:
            messages.error(request, 'As senhas não coincidem.')
        elif User.objects.filter(email=email).exists():
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
    context.update(noindex_context(request, 'Criar conta - Barrs Store'))
    return render(request, 'cadastro.html', context)


# ── LOGIN ──────────────────────────────────────────────────────────
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def login_view(request):
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        if not verificar_turnstile(request):
            messages.error(request, 'Confirme a verificacao de seguranca e tente novamente.')
            context = {'qtd_carrinho': get_carrinho_info(request)}
            context.update(noindex_context(request, 'Login - Barrs Store'))
            return render(request, 'login.html', context)

        email = request.POST.get('email', '').strip()
        senha = request.POST.get('senha', '')
        user = authenticate(request, username=email, password=senha)
        if user:
            login(request, user)
            next_url = request.GET.get('next', 'minha_conta')
            return redirect(next_url)
        else:
            messages.error(request, 'E-mail ou senha incorretos.')

    context = {'qtd_carrinho': get_carrinho_info(request)}
    context.update(noindex_context(request, 'Login - Barrs Store'))
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

    context = {
        'perfil': perfil,
        'pedidos': pedidos,
        'qtd_carrinho': get_carrinho_info(request),
    }
    context.update(noindex_context(request, 'Minha conta - Barrs Store'))
    return render(request, 'minha_conta.html', context)


# ── DETALHE DO PEDIDO (cliente) ────────────────────────────────────
@login_required(login_url='/login/')
def detalhe_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, cliente=request.user)
    context = {
        'pedido': pedido,
        'qtd_carrinho': get_carrinho_info(request),
    }
    context.update(noindex_context(request, f'Pedido #{pedido.id} - Barrs Store'))
    return render(request, 'detalhe_pedido.html', context)


# ── PÁGINAS ESTÁTICAS ──────────────────────────────────────────────
def robots_txt(request):
    linhas = [
        'User-agent: *',
        'Disallow: /painel/',
        'Disallow: /admin/',
        'Disallow: /carrinho/',
        'Disallow: /finalizar/',
        'Disallow: /pagamento/',
        'Disallow: /minha-conta/',
        'Disallow: /login/',
        'Disallow: /cadastro/',
        'Allow: /',
        f'Sitemap: {site_url("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(linhas), content_type='text/plain')


def google_site_verification(request):
    return HttpResponse(
        'google-site-verification: google86e9062d166d5e41.html',
        content_type='text/html',
    )


def pagina_404(request, exception):
    return render(request, '404.html', status=404)


def entrega(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Entrega e trocas - Barrs Store', 'Veja prazos de envio e informacoes de trocas e devolucoes da Barrs Store para comprar com tranquilidade.'),
    }
    return render(request, 'entrega.html', context)


def medidas(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Guia de medidas - Barrs Store', 'Consulte o guia de medidas da Barrs Store para escolher aneis e acessorios com mais seguranca.'),
    }
    return render(request, 'medidas.html', context)


def garantia(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(
            request,
            'Garantia Barrs Store - Semijoias com 12 meses de garantia',
            'Entenda a garantia de 12 meses da Barrs Store, o que cobre, o que nao cobre e como cuidar das suas semijoias.',
        ),
    }
    return render(request, 'garantia.html', context)


@ratelimit(key='ip', rate='10/m', method='GET', block=True)
def rastrear_pedido(request):
    pedido = None
    erro = ''
    if request.GET.get('pedido') or request.GET.get('email'):
        pedido_id = request.GET.get('pedido', '').strip().replace('#', '')
        email = request.GET.get('email', '').strip()
        if not pedido_id or not email:
            erro = 'Informe o numero do pedido e o e-mail da compra.'
        else:
            try:
                pedido = Pedido.objects.get(id=pedido_id, email__iexact=email)
            except (Pedido.DoesNotExist, ValueError):
                erro = 'Nao encontramos um pedido com esses dados.'

    context = {
        'pedido': pedido,
        'erro': erro,
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Rastrear pedido - Barrs Store', 'Acompanhe o status e o codigo de rastreio do seu pedido na Barrs Store.'),
    }
    return render(request, 'rastrear_pedido.html', context)


def sobre(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Sobre a Barrs Store', 'Conheca a Barrs Store, uma loja de acessorios modernos com atendimento humanizado e rapido.'),
    }
    return render(request, 'sobre.html', context)


def contato(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Contato - Barrs Store', 'Fale com a Barrs Store pelo WhatsApp para tirar duvidas sobre produtos, pedidos e entregas.'),
    }
    return render(request, 'contato.html', context)


def politica(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Politica de privacidade - Barrs Store', 'Leia a politica de privacidade da Barrs Store e entenda como seus dados sao protegidos.'),
    }
    return render(request, 'politica.html', context)
