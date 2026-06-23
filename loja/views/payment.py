import hashlib
import json
import logging
import os

import mercadopago
from requests.exceptions import RetryError, RequestException

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ..models import Cupom, Pedido, Produto, TamanhoAnel
from ..mercadopago_security import validar_assinatura_mercadopago
from ..integrations.meta_capi import send_purchase_event
from .utils import (
    apenas_digitos,
    get_pedido_por_token,
    no_tracking_context,
    noindex_context,
    payload_pagamento_seguro_para_log,
    ratelimit,
    site_url,
)
from .emails import enviar_email_confirmacao
from .shipping import criar_envio_melhor_envio

logger = logging.getLogger(__name__)

# Tabela de erros do Mercado Pago no estilo das grandes marcas (Stripe, Magalu, Amazon):
# - 'categoria': "transient" (instabilidade), "cartao" (dado errado do cliente), "banco" (banco recusou).
# - 'pode_tentar': True se o cliente deve tentar de novo com os mesmos dados.
# - 'mensagem': texto curto, claro, sem jargao tecnico.
# - 'sugestao': proximo passo concreto.
_MP_ERROS = {
    'cc_rejected_insufficient_amount': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Saldo insuficiente no cartao.',
        'sugestao': 'Use outro cartao ou pague no Pix.',
    },
    'cc_rejected_bad_filled_security_code': {
        'categoria': 'cartao',
        'pode_tentar': True,
        'mensagem': 'Codigo de seguranca invalido.',
        'sugestao': 'Confira o CVV (3 ou 4 numeros no verso do cartao).',
    },
    'cc_rejected_bad_filled_date': {
        'categoria': 'cartao',
        'pode_tentar': True,
        'mensagem': 'Data de validade incorreta.',
        'sugestao': 'Confira mes e ano de vencimento impressos no cartao.',
    },
    'cc_rejected_bad_filled_card_number': {
        'categoria': 'cartao',
        'pode_tentar': True,
        'mensagem': 'Numero do cartao invalido.',
        'sugestao': 'Revise os 16 digitos do cartao e tente novamente.',
    },
    'cc_rejected_bad_filled_other': {
        'categoria': 'cartao',
        'pode_tentar': True,
        'mensagem': 'Algum dado do cartao esta incorreto.',
        'sugestao': 'Revise os campos do cartao e tente de novo.',
    },
    'cc_rejected_high_risk': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Pagamento recusado por seguranca.',
        'sugestao': 'Use outro cartao ou pague no Pix.',
    },
    'cc_rejected_card_disabled': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Cartao desabilitado.',
        'sugestao': 'Entre em contato com seu banco ou use outro cartao.',
    },
    'cc_rejected_call_for_authorize': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Seu banco precisa autorizar essa compra.',
        'sugestao': 'Ligue para o telefone no verso do cartao e libere o valor.',
    },
    'cc_rejected_duplicated_payment': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Pagamento ja identificado.',
        'sugestao': 'Confira no app do seu banco antes de tentar novamente.',
    },
    'cc_rejected_card_type_not_allowed': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Esse tipo de cartao nao e aceito.',
        'sugestao': 'Use outro cartao ou pague no Pix.',
    },
    'cc_rejected_max_attempts': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Limite de tentativas atingido neste cartao.',
        'sugestao': 'Aguarde 30 minutos ou use outro cartao.',
    },
    'cc_rejected_other_reason': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Pagamento recusado pelo banco.',
        'sugestao': 'Use outro cartao ou pague no Pix.',
    },
    'cc_rejected_blacklist': {
        'categoria': 'banco',
        'pode_tentar': False,
        'mensagem': 'Pagamento recusado.',
        'sugestao': 'Use outro cartao ou pague no Pix.',
    },
}

_MP_ERRO_TRANSIENT = {
    'categoria': 'transient',
    'pode_tentar': True,
    'mensagem': 'Instabilidade momentanea no pagamento.',
    'sugestao': 'Aguarde alguns segundos e clique em Tentar novamente.',
}

_MP_ERRO_GENERICO = {
    'categoria': 'banco',
    'pode_tentar': True,
    'mensagem': 'Pagamento nao aprovado.',
    'sugestao': 'Confira os dados ou use outro cartao. Voce tambem pode pagar no Pix.',
}


def interpretar_erro_mp(status_code, payment):
    """Traduz erros do Mercado Pago em mensagem amigavel + categoria + sugestao."""
    detail = (payment or {}).get('status_detail') or ''
    if detail and detail in _MP_ERROS:
        return _MP_ERROS[detail]
    # 5xx ou message='internal_error' = instabilidade do MP.
    message = ((payment or {}).get('message') or '').lower()
    if status_code >= 500 or 'internal_error' in message or 'timeout' in message:
        return _MP_ERRO_TRANSIENT
    return _MP_ERRO_GENERICO


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


def dados_pagador_mercadopago(pedido):
    """Monta os dados do pagador sem confiar em dados digitados no frontend.

    Raises:
        ValueError: se o pedido nao tem email. O checkout valida email como
            obrigatorio, entao um pedido sem email indica bug em outro lugar —
            falhar cedo evita usar o email da loja como pagador (anomalia que
            mascarava o defeito).
    """
    if not pedido.email:
        raise ValueError(f'Pedido {pedido.id} sem email; nao e possivel iniciar pagamento.')

    telefone_limpo = "".join(filter(str.isdigit, pedido.telefone or ""))
    cpf_limpo = apenas_digitos(pedido.cpf)
    partes_nome = (pedido.nome or '').strip().split()

    # Em DEBUG, o MP sandbox rejeita e-mails reais (500) e o e-mail do vendedor
    # (403 code 4390). Usa um e-mail de comprador de teste se configurado.
    email_pagador = pedido.email
    if settings.DEBUG:
        email_pagador = getattr(settings, 'MP_TEST_BUYER_EMAIL', None) or pedido.email

    payer = {
        "name": pedido.nome,
        "first_name": partes_nome[0] if partes_nome else pedido.nome,
        "last_name": " ".join(partes_nome[1:]) if len(partes_nome) > 1 else "",
        "email": email_pagador,
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


def _telefone_mp(pedido):
    """Telefone no formato {area_code, number} aceito pelo MP, ou None."""
    telefone_limpo = "".join(filter(str.isdigit, pedido.telefone or ""))
    if len(telefone_limpo) >= 10:
        return {"area_code": telefone_limpo[:2], "number": telefone_limpo[2:]}
    return None


def additional_info_pagador_mp(pedido):
    """Bloco payer do additional_info — sinal extra para o antifraude do MP.

    Diferente do payer principal (que carrega token e identification), este e
    puramente informativo (nome, telefone e endereco) e ajuda o MP a validar
    a compra. So preenche o que existe — nunca quebra se faltar dado.

    IMPORTANTE: NAO enviamos registration_date. O checkout cria a conta no
    momento do pedido, entao a data de cadastro seria sempre "agora" — o MP
    interpreta comprador recem-cadastrado como alto risco e recusa TODOS os
    pagamentos (cc_rejected_high_risk). Omitir e melhor que enviar data falsa.
    """
    partes_nome = (pedido.nome or '').strip().split()
    info = {
        "first_name": partes_nome[0] if partes_nome else pedido.nome,
        "last_name": " ".join(partes_nome[1:]) if len(partes_nome) > 1 else "",
    }
    telefone = _telefone_mp(pedido)
    if telefone:
        info["phone"] = telefone
    if pedido.cep and pedido.rua and pedido.numero:
        info["address"] = {
            "zip_code": apenas_digitos(pedido.cep),
            "street_name": pedido.rua,
            "street_number": pedido.numero,
        }
    return info


def shipments_receiver_address_mp(pedido):
    """Endereco de entrega para o MP (shipments.receiver_address).

    O MP avalia este bloco separado do payer.address, tanto no antifraude
    quanto na nota de qualidade da integracao. Retorna None se faltar o
    endereco minimo (cep/rua/numero)."""
    if not (pedido.cep and pedido.rua and pedido.numero):
        return None
    endereco = {
        "zip_code": apenas_digitos(pedido.cep),
        "street_name": pedido.rua,
        "street_number": pedido.numero,
        "city_name": pedido.cidade,
        "state_name": pedido.estado,
    }
    if pedido.complemento:
        endereco["apartment"] = pedido.complemento
    return endereco


def categoria_item_mp(item):
    """category_id do item para o antifraude do MP.

    Usa o nome da categoria real do produto quando existe; senao 'others'
    (valor neutro aceito pelo MP). Apenas informativo — nao afeta a UI."""
    produto = item.produto
    if produto and produto.categoria_id and produto.categoria:
        return produto.categoria.nome
    return 'others'


def descricao_item_mp(item):
    """Descricao por item para o antifraude do Mercado Pago.

    O suporte do MP recomenda enviar items.description para validar melhor a
    compra e reduzir recusas por alto risco (cc_rejected_high_risk). Usa a
    descricao real do produto; se vazia, compoe categoria + nome; em ultimo
    caso usa so o nome. Texto apenas para o backend do MP — nao afeta a UI.
    """
    produto = item.produto
    if produto and (produto.descricao or '').strip():
        # Colapsa quebras de linha/espacos do TextField num texto de uma linha.
        texto = ' '.join(produto.descricao.split())
    elif produto and produto.categoria_id and produto.categoria:
        texto = f'{produto.categoria.nome} - {item.nome_produto}'
    else:
        texto = item.nome_produto
    # MP limita a descricao; corta com folga para nao ser rejeitado por tamanho.
    return texto[:256]


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

    if pedido.frete_transportadora == 'lalamove':
        logger.info('[PAGAMENTO] Pedido %s usa Lalamove — entrega aguarda solicitação manual no admin.', pedido.id)
    else:
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
    try:
        payment_info = sdk.payment().get(payment_id)
    except (RetryError, RequestException) as exc:
        logger.error(
            '[PAGAMENTO] Falha de rede ao consultar Mercado Pago payment_id=%s: %s',
            payment_id,
            exc,
        )
        return False
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
        # Guard critico: webhook tardio de uma tentativa rejeitada nao pode
        # sobrescrever um pedido que ja foi confirmado por outra tentativa.
        if pedido.status == 'confirmado':
            logger.warning(
                '[PAGAMENTO] Webhook %s ignorado: pedido %s ja esta confirmado. payment_id=%s detail=%s',
                status, pedido.id, payment_id, status_detail,
            )
            return True
        pedido.status = "cancelado"
        pedido.save(update_fields=['status'])
        logger.warning('[PAGAMENTO] Pedido %s cancelado/rejeitado. status=%s detail=%s', pedido.id, status, status_detail)
        return True

    if status in ["refunded", "charged_back"]:
        # Estorno ou chargeback de pedido confirmado: precisa atencao manual
        # (verificar envio, restaurar estoque, etc). Logamos ERROR para alertar.
        logger.error(
            '[PAGAMENTO] Pedido %s recebeu evento %s (payment_id=%s detail=%s). '
            'ACAO MANUAL NECESSARIA: verificar envio, estorno e estoque.',
            pedido.id, status, payment_id, status_detail,
        )
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


# ── VIEWS DE PAGAMENTO ─────────────────────────────────────────────

def confirmacao(request, pedido_id, token):
    from django.shortcuts import render, redirect
    pedido = get_pedido_por_token(pedido_id, token)
    if pedido.status == 'confirmado':
        return redirect('pagamento_sucesso', pedido_id=pedido.id, token=pedido.access_token)
    context = {
        'pedido': pedido,
        'mp_public_key': settings.MERCADOPAGO_PUBLIC_KEY,
    }
    context.update(noindex_context(request, f'Pedido #{pedido.id} - Barrs Store'))
    return render(request, 'confirmacao.html', context)


def _pedido_acessivel_por(request, pedido):
    """Defense-in-depth: se o usuario esta logado e o pedido tem dono,
    bloqueia qualquer tentativa de iniciar pagamento com token de outro
    cliente (cenario de access_token vazado em log/screenshot/suporte).
    Guest checkout (pedido.cliente_id None) continua funcionando."""
    if not request.user.is_authenticated:
        return True
    if pedido.cliente_id is None:
        return True
    return pedido.cliente_id == request.user.id


@require_POST
@ratelimit(key='ip', rate='15/m', method='POST', block=True)
def criar_preferencia(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    if not _pedido_acessivel_por(request, pedido):
        logger.warning('[PAGAMENTO] Tentativa de pagar pedido alheio. pedido=%s user=%s', pedido.id, request.user.id)
        return JsonResponse({'erro': 'Acesso negado.'}, status=403)
    if not settings.MERCADOPAGO_ACCESS_TOKEN:
        return JsonResponse({'erro': 'Mercado Pago nao configurado.'}, status=503)
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

    items = []
    if pedido.desconto > 0:
        # Linha unica (cupom aplicado): descreve os produtos reais do pedido
        # para o antifraude do MP, mesmo sem detalhar preco por item.
        nomes_produtos = ', '.join(
            i.nome_produto for i in pedido.itens.all()
        )[:256] or f'Pedido #{pedido.id} - Barrs Store'
        items.append({
            "title": f"Pedido #{pedido.id} - Barrs Store",
            "description": nomes_produtos,
            "quantity": 1,
            "unit_price": float(pedido.total),
            "currency_id": "BRL",
        })
    else:
        for item in pedido.itens.select_related('produto', 'produto__categoria').all():
            items.append({
                "id": str(item.produto_id or item.id),
                "title": item.nome_produto,
                "description": descricao_item_mp(item),
                "category_id": categoria_item_mp(item),
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
    try:
        payer = dados_pagador_mercadopago(pedido)
    except ValueError as exc:
        logger.error('[PAGAMENTO] %s', exc)
        return JsonResponse({'erro': 'Pedido sem email. Refaca o checkout.'}, status=400)

    preference_data = {
        "items": items,
        "payer": payer,
        "back_urls": {
            "success": site_url(reverse('pagamento_sucesso', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
            "failure": site_url(reverse('pagamento_falha', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
            "pending": site_url(reverse('pagamento_pendente', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token})),
        },
        "external_reference": str(pedido.id),
        "metadata": {
            "pedido_id": pedido.id,
        },
        "statement_descriptor": "BARRS STORE",
    }
    # Endereco de entrega: o MP avalia shipments.receiver_address separado do
    # payer.address (antifraude + nota de qualidade da integracao).
    receiver_address = shipments_receiver_address_mp(pedido)
    if receiver_address:
        preference_data["shipments"] = {"receiver_address": receiver_address}
    # Em dev (DEBUG=True) o MP recusa auto_return apontando para dominio
    # nao publico. Notificacoes chegam apenas pelo webhook configurado no
    # painel do MP; notification_url gerava duplicatas com assinatura propria
    # que falhavam na validacao (403 + retries).
    if not settings.DEBUG:
        preference_data["auto_return"] = "approved"

    try:
        preference_response = sdk.preference().create(preference_data)
    except (RetryError, RequestException) as exc:
        logger.error('Falha de rede ao criar preferencia MP pedido=%s: %s', pedido.id, exc)
        return JsonResponse({'erro': 'Pagamento indisponivel no momento. Tente novamente.'}, status=502)
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
    if not _pedido_acessivel_por(request, pedido):
        logger.warning('[PAGAMENTO] Tentativa de pagar pedido alheio via Brick. pedido=%s user=%s', pedido.id, request.user.id)
        return JsonResponse({'erro': 'Acesso negado.'}, status=403)
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
    try:
        payer = dados_pagador_mercadopago(pedido)
    except ValueError as exc:
        logger.error('[PAGAMENTO] %s', exc)
        return JsonResponse({'erro': 'Pedido sem email. Refaca o checkout.'}, status=400)
    # A API de pagamento direto do Brick rejeita payer.name; usa first_name/last_name.
    payer.pop('name', None)
    # Sempre usa o email do pedido (token UUID ja garante autoria); ignora o que vier do front.
    if not payer.get('identification') and isinstance(payer_front.get('identification'), dict):
        payer['identification'] = payer_front['identification']

    # Pix paga com desconto (total_pix); cartão e demais métodos pagam o total.
    # O total do pedido no banco não muda: o desconto vale só na transação.
    metodo_escolhido = form_data.get('payment_method_id')
    tipo_escolhido = form_data.get('payment_type_id', '')
    tem_token = bool(form_data.get('token'))
    logger.info(
        '[MP-BRICK] Metodo recebido pedido=%s payment_method_id=%r payment_type_id=%r tem_token=%s',
        pedido.id, metodo_escolhido, tipo_escolhido, tem_token,
    )
    # Pix: method_id=='pix' OU type_id=='bank_transfer', nunca tem token de cartão.
    pagamento_pix = (
        metodo_escolhido == 'pix' or tipo_escolhido == 'bank_transfer'
    ) and not tem_token
    valor_cobranca = pedido.total_pix if pagamento_pix else pedido.total
    logger.info(
        '[MP-BRICK] %s pedido=%s subtotal=%s desconto=%s frete=%s total=%s valor_cobranca=%s',
        'Pix com desconto' if pagamento_pix else 'Cartao/outro',
        pedido.id, pedido.subtotal, pedido.desconto, pedido.frete, pedido.total, valor_cobranca,
    )

    # additional_info.items: detalhe por produto (com description) para o
    # antifraude do MP validar a compra e reduzir cc_rejected_high_risk.
    # E informativo — nao precisa somar o transaction_amount (que muda no Pix).
    info_items = []
    for item in pedido.itens.select_related('produto', 'produto__categoria').all():
        info_items.append({
            'id': str(item.produto_id or item.id),
            'title': item.nome_produto,
            'description': descricao_item_mp(item),
            'category_id': categoria_item_mp(item),
            'quantity': int(item.quantidade),
            'unit_price': float(item.preco_unitario),
        })

    payment_data = {
        'transaction_amount': float(valor_cobranca),
        'description': f'Pedido #{pedido.id} - Barrs Store',
        'payment_method_id': metodo_escolhido,
        'payer': payer,
        'external_reference': str(pedido.id),
        'metadata': {
            'pedido_id': pedido.id,
        },
        'statement_descriptor': 'BARRS STORE',
    }
    # additional_info: items (detalhe por produto), payer (com registration_date)
    # e shipments.receiver_address (endereco de entrega). O MP usa esses blocos
    # para validar a compra e melhorar a nota de qualidade da integracao.
    additional_info = {}
    if info_items:
        additional_info['items'] = info_items
    additional_info['payer'] = additional_info_pagador_mp(pedido)
    receiver_address = shipments_receiver_address_mp(pedido)
    if receiver_address:
        additional_info['shipments'] = {'receiver_address': receiver_address}
    if additional_info:
        payment_data['additional_info'] = additional_info
    # Notificacoes chegam apenas pelo webhook configurado no painel do MP;
    # notification_url gerava duplicatas com assinatura propria que falhavam
    # na validacao (403 + retries).

    # Cartao usa token/parcelas/emissor. Pix nao precisa desses campos.
    if form_data.get('token'):
        payment_data['token'] = form_data.get('token')
    if form_data.get('installments'):
        try:
            n = int(form_data.get('installments'))
        except (TypeError, ValueError):
            n = 1
        # Clamp em [1, 12]: o Brick controla isso no front, mas o body e JSON
        # livre e um cliente pode injetar installments=999. Aqui evitamos
        # poluir logs com tentativas absurdas.
        payment_data['installments'] = max(1, min(12, n))
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

    # DEBUG (nao INFO) — payment_method_id + payload sao dados pessoais indiretos
    # sob LGPD. Em produsao, ativar so quando investigando incidente especifico.
    logger.debug(
        '[MP-BRICK] Criando pagamento pedido=%s metodo=%s total=%s',
        pedido.id,
        payment_data.get('payment_method_id'),
        pedido.total,
    )
    logger.debug(
        '[MP-BRICK] Payload seguro pedido=%s: %s',
        pedido.id,
        payload_pagamento_seguro_para_log(payment_data),
    )
    # Log resumido em INFO: so o ID do pedido, sem revelar metodo de pagamento.
    logger.info('[MP-BRICK] Iniciando pagamento pedido=%s total=%s', pedido.id, pedido.total)
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    request_options = mercadopago.config.RequestOptions()
    # Idempotency-Key estavel: mesma combinacao pedido+metodo+token+parcelas
    # gera a mesma chave (MP dedupe double-click). Tentativa nova (outro cartao,
    # outro Pix) gera chave diferente e e aceita como novo pagamento.
    idem_seed = '|'.join([
        str(pedido.id),
        str(payment_data.get('payment_method_id') or ''),
        str(payment_data.get('token') or '')[:32],
        str(payment_data.get('installments') or ''),
    ])
    custom_headers = {
        'X-Idempotency-Key': hashlib.sha256(idem_seed.encode('utf-8')).hexdigest(),
    }
    # Device ID coletado pelo security.js no front (window.MP_DEVICE_SESSION_ID).
    # Repassado como X-meli-session-id melhora a aprovacao antifraude do MP.
    # Se o script nao carregou, segue sem o header — nao trava o checkout.
    device_id = (form_data.get('device_id') or '').strip()
    if device_id:
        custom_headers['X-meli-session-id'] = device_id
    else:
        logger.warning(
            '[MP-BRICK] Device ID ausente no pedido %s; pagamento seguira sem '
            'X-meli-session-id (maior risco de recusa antifraude).',
            pedido.id,
        )
    request_options.custom_headers = custom_headers
    try:
        payment_response = sdk.payment().create(payment_data, request_options)
    except (RetryError, RequestException) as exc:
        logger.error('[MP-BRICK] Falha de rede ao criar pagamento pedido=%s: %s', pedido.id, exc)
        return JsonResponse({
            'erro': 'Pagamento indisponivel no momento. Tente novamente em instantes.',
            'sugestao': 'Se persistir, escolha outra forma de pagamento.',
            'categoria': 'transient',
            'pode_tentar': True,
        }, status=502)
    payment = payment_response.get('response', {})
    status_code = payment_response.get('status', 500)

    if status_code >= 400:
        logger.warning(
            '[MP-BRICK] Falha ao criar pagamento pedido=%s status=%s resposta=%s',
            pedido.id,
            status_code,
            resumir_erro_mercadopago(payment),
        )
        # Payload com metodo/parcelas/issuer fica em DEBUG: dados indiretos LGPD.
        logger.debug(
            '[MP-BRICK] Payload que falhou pedido=%s: %s',
            pedido.id,
            payload_pagamento_seguro_para_log(payment_data),
        )
        info = interpretar_erro_mp(status_code, payment)
        return JsonResponse({
            'erro': info['mensagem'],
            'sugestao': info['sugestao'],
            'categoria': info['categoria'],
            'pode_tentar': info['pode_tentar'],
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

    # Registra o método real e o desconto Pix efetivamente cobrado.
    # Feito antes da confirmação para que o Purchase da CAPI use o valor cobrado.
    forma_real = 'pix' if pagamento_pix else 'cartao'
    campos_registrar = {}
    if pedido.forma_pagamento != forma_real:
        campos_registrar['forma_pagamento'] = forma_real
    if pagamento_pix and pedido.desconto_pix_aplicado == 0:
        campos_registrar['desconto_pix_aplicado'] = pedido.desconto_pix
    if campos_registrar:
        Pedido.objects.filter(pk=pedido.pk).update(**campos_registrar)
        pedido.refresh_from_db()

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
    from django.shortcuts import render, redirect
    pedido = get_pedido_por_token(pedido_id, token)
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id and pedido.status != 'confirmado':
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    # Evita renderizar tela de "sucesso" se o pagamento nao foi de fato
    # aprovado (MP fora, webhook atrasado). Manda pro pendente, onde o
    # polling atualiza assim que o status chegar.
    if pedido.status != 'confirmado':
        return redirect('pagamento_pendente', pedido_id=pedido.id, token=pedido.access_token)
    meta_purchase_value = max(pedido.total - pedido.desconto_pix_aplicado, 0)
    context = {
        'pedido': pedido,
        'meta_event_id': f'purchase_{pedido.id}',
        'meta_purchase_value': meta_purchase_value,
    }
    context.update(noindex_context(request, 'Pagamento - Barrs Store'))
    return render(request, 'pagamento_sucesso.html', context)


@ratelimit(key='ip', rate='30/m', method='GET', block=False)
def pagamento_falha(request, pedido_id, token):
    from django.shortcuts import render
    pedido = get_pedido_por_token(pedido_id, token)
    # Se MP devolveu payment_id na URL e o pedido ainda nao foi resolvido,
    # tenta sincronizar para nao deixar o pedido eternamente em "pendente".
    # O guard em confirmar_pagamento_mercadopago evita sobrescrever 'confirmado'.
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id and pedido.status not in ('confirmado', 'cancelado'):
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    context = {'pedido': pedido}
    context.update(no_tracking_context(request, 'Pagamento nao aprovado - Barrs Store'))
    return render(request, 'pagamento_falha.html', context)


@ratelimit(key='ip', rate='30/m', method='GET', block=False)
def pagamento_pendente(request, pedido_id, token):
    from django.shortcuts import render
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
    from django.core.cache import cache
    data = {}
    try:
        if request.body:
            data = json.loads(request.body)
    except json.JSONDecodeError:
        data = {}

    # Dedupe por x-request-id: MP reentrega o mesmo webhook varias vezes.
    # cache.add e atomico — primeira chamada ganha, demais sao ignoradas.
    # Funcoes internas ja sao idempotentes (select_for_update + flags), mas
    # isso evita consultar a API MP repetidamente e consumir quota.
    request_id_mp = request.headers.get('x-request-id', '')
    if request_id_mp:
        if not cache.add(f'mp:wh:{request_id_mp}', '1', 24 * 60 * 60):
            logger.info('[MP] Webhook duplicado ignorado: x-request-id=%s', request_id_mp)
            return HttpResponse(status=200)

    assinatura_ok, motivo_assinatura = validar_assinatura_mercadopago(request, data)
    if not assinatura_ok:
        logger.warning('[MP] Webhook com assinatura nao validada: %s', motivo_assinatura)
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
        try:
            confirmar_pagamento_mercadopago(payment_id)
        except Exception as exc:
            logger.exception('[MP] Erro ao confirmar pagamento webhook payment_id=%s: %s', payment_id, exc)
    elif notification_type == "merchant_order" and payment_id:
        try:
            confirmar_merchant_order_mercadopago(payment_id)
        except Exception as exc:
            logger.exception('[MP] Erro ao confirmar merchant_order webhook id=%s: %s', payment_id, exc)

    return HttpResponse(status=200)
