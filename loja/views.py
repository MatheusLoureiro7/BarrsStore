from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, F
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from .models import Produto, Carrinho, ItemCarrinho, Pedido, ItemPedido, PerfilCliente, Categoria, Cupom
from .mercadopago_security import validar_assinatura_mercadopago
from .validators import cpf_valido
import mercadopago
import json
import requests as http_requests
import os
import logging
from decimal import Decimal, InvalidOperation

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
    return f"{base}{path if path.startswith('/') else '/' + path}"


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


def confirmar_pedido_pago(pedido):
    atualizou = False
    if pedido.status != 'confirmado':
        pedido.status = 'confirmado'
        atualizou = True
        if pedido.cupom_codigo:
            Cupom.objects.filter(codigo__iexact=pedido.cupom_codigo).update(usado=F('usado') + 1)

    if not pedido.email_confirmacao_enviado:
        enviado = enviar_email_confirmacao(pedido)
        if enviado:
            pedido.email_confirmacao_enviado = True
            atualizou = True

    if atualizou:
        pedido.save(update_fields=['status', 'email_confirmacao_enviado'])

    criar_envio_melhor_envio(pedido)


def confirmar_pagamento_mercadopago(payment_id):
    if not payment_id or not settings.MERCADOPAGO_ACCESS_TOKEN:
        return False

    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    payment_info = sdk.payment().get(payment_id)
    if payment_info.get("status", 500) >= 400:
        logger.warning('Falha ao consultar pagamento Mercado Pago %s: %s', payment_id, payment_info)
        return False

    payment = payment_info.get("response", {})

    pedido_id = payment.get("external_reference")
    status = payment.get("status")

    if not pedido_id:
        logger.warning('Mercado Pago sem external_reference no pagamento %s.', payment_id)
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
        pedido.status = "pendente"
        pedido.save(update_fields=['status'])
        return True
    if status in ["cancelled", "rejected"]:
        pedido.status = "cancelado"
        pedido.save(update_fields=['status'])
        return True

    logger.info('Pagamento Mercado Pago %s recebido com status %s.', payment_id, status)
    return False


def confirmar_merchant_order_mercadopago(merchant_order_id):
    if not merchant_order_id or not settings.MERCADOPAGO_ACCESS_TOKEN:
        return False

    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)
    order_info = sdk.merchant_order().get(merchant_order_id)
    if order_info.get("status", 500) >= 400:
        logger.warning('Falha ao consultar merchant_order Mercado Pago %s: %s', merchant_order_id, order_info)
        return False

    order = order_info.get("response", {})
    pagamentos = order.get("payments") or []
    confirmou = False
    for pagamento in pagamentos:
        payment_id = pagamento.get("id")
        if payment_id:
            confirmou = confirmar_pagamento_mercadopago(payment_id) or confirmou

    if not pagamentos:
        logger.info('Merchant order Mercado Pago %s ainda sem pagamentos vinculados.', merchant_order_id)
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
    peso_total = max(Decimal('0.3'), Decimal('0.3') * sum(item.quantidade for item in pedido.itens.all()))

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
            for item in pedido.itens.all()
        ],
        'volumes': [{
            'height': 4,
            'width': 11,
            'length': 16,
            'weight': float(peso_total),
        }],
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
        logger.info('[ME] Criar envio pedido %s: status=%s body=%s', pedido.id, resposta.status_code, texto)

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
                <div style="width:64px;height:64px;background:#E8EDE3;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:28px;margin-bottom:16px">✓</div>
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
                <a href="https://wa.me/5511913225256" style="display:inline-block;padding:12px 28px;background:#25d366;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">💬 WhatsApp</a>
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

        logger.info('[BREVO] Iniciando envio do pedido %s para %s', pedido.id, pedido.email)
        brevo_from_email = os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip()
        brevo_admin_email = os.environ.get('BREVO_ADMIN_EMAIL', brevo_from_email).strip()
        payload = {
            'sender': {
                'name': 'Barrs Store',
                'email': brevo_from_email,
            },
            'to': [{'email': pedido.email, 'name': pedido.nome}],
            'subject': f'✓ Pedido #{pedido.id} confirmado — Barrs Store',
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
        logger.info('[BREVO] Resposta pedido %s: status=%s body=%s', pedido.id, resposta.status_code, resposta.text[:500])
        if resposta.status_code >= 400:
            logger.warning(
                'Brevo recusou o e-mail do pedido %s. Status %s: %s',
                pedido.id,
                resposta.status_code,
                resposta.text[:500],
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
        logger.info('[BREVO] Pagamento pendente pedido %s: status=%s body=%s', pedido.id, resposta.status_code, resposta.text[:300])
        if resposta.status_code < 400:
            pedido.email_pagamento_pendente_enviado = True
            pedido.save(update_fields=['email_pagamento_pendente_enviado'])
            return True
        logger.warning(
            'Brevo recusou o e-mail de pagamento pendente do pedido %s. Status %s: %s',
            pedido.id,
            resposta.status_code,
            resposta.text[:500],
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
                    <p>Você pode acompanhar a entrega pelo botão abaixo.</p>
                    <a href="{rastreio_url}" style="display:inline-block;background:#8A947C;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600">Acompanhar entrega</a>
                  </div>
                </div>
                """,
            },
            timeout=10,
        )
        logger.info('[BREVO] Rastreio pedido %s: status=%s body=%s', pedido.id, resposta.status_code, resposta.text[:300])
        if resposta.status_code >= 400:
            logger.warning(
                'Brevo recusou o e-mail de rastreio do pedido %s. Status %s: %s',
                pedido.id,
                resposta.status_code,
                resposta.text[:500],
            )
            return False
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de rastreio do pedido %s: %s', pedido.id, exc)
        return False


# ── WHATSAPP: NOTIFICAÇÃO DE NOVO PEDIDO ──────────────────────────
def enviar_whatsapp_pedido(pedido):
    """Envia notificação no WhatsApp quando chegar um novo pedido."""
    try:
        itens_texto = ', '.join(
            f"{item.quantidade}x {item.nome_produto}{f' - Tam. {item.tamanho}' if item.tamanho else ''}"
            for item in pedido.itens.all()
        )

        frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Grátis"

        mensagem = (
            f"🛍️ NOVO PEDIDO #{pedido.id}\n\n"
            f"👤 {pedido.nome}\n"
            f"📱 {pedido.telefone}\n"
            f"📧 {pedido.email}\n\n"
            f"📦 Itens: {itens_texto}\n\n"
            f"💰 Subtotal: R$ {pedido.subtotal}\n"
            f"🚚 Frete: {frete_texto}\n"
            f"💎 Total: R$ {pedido.total}\n\n"
            f"💳 Pagamento: {pedido.get_forma_pagamento_display()}\n"
            f"📍 Endereço: {pedido.rua}, {pedido.numero} - {pedido.cidade}/{pedido.estado}"
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

    categorias = Categoria.objects.all()
    seo = seo_context(
        request,
        'Barrs Store - Acessorios modernos e exclusivos',
        'Compre acessorios femininos modernos na Barrs Store: aneis, brincos, colares e pulseiras com envio para todo o Brasil.'
    )

    context = {
        'produtos': produtos,
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': produtos.count(),
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
    }
    context.update(seo)
    return render(request, 'home.html', context)


# ── DETALHE DO PRODUTO ─────────────────────────────────────────────
def detalhe_produto(request, slug):
    produto = get_object_or_404(Produto, slug=slug)
    relacionados = Produto.objects.filter(visivel=True, categoria=produto.categoria).exclude(id=produto.id)[:4]
    if not relacionados:
        relacionados = Produto.objects.filter(visivel=True).exclude(id=produto.id)[:4]
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
    produto = get_object_or_404(Produto, id=produto_id)
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


# ── CALCULAR FRETE VIA CEP (AJAX) ─────────────────────────────────
@ratelimit(key='ip', rate='30/m', method='GET', block=True)
def calcular_frete_ajax(request):
    """Frete fixo/regional desativado. Use sempre o Melhor Envio."""
    return JsonResponse({
        'erro': 'Frete fixo desativado. Calcule o frete no carrinho pelo Melhor Envio.'
    }, status=410)


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
        payload = {
            'from': {'postal_code': apenas_digitos(os.environ.get('ME_REMETENTE_CEP', '08275700'))},
            'to': {'postal_code': cep_destino},
            'package': {
                'height': 4,
                'width': 11,
                'length': 16,
                'weight': 0.3,
            },
            'options': {
                'receipt': False,
                'own_hand': False,
            },
        }

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
        
        for servico in data:
            if 'error' not in servico and servico.get('price'):
                opcoes.append({
                    'id': servico.get('id'),
                    'nome': servico.get('name', ''),
                    'empresa': servico.get('company', {}).get('name', ''),
                    'preco': float(servico.get('price', 0)),
                    'prazo': servico.get('delivery_time', ''),
                })
        
        opcoes.sort(key=lambda x: x['preco'])
        return JsonResponse({'opcoes': opcoes})
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


# ── ADICIONAR AO CARRINHO ──────────────────────────────────────────
@require_POST
def adicionar_carrinho(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
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

    item, criado = ItemCarrinho.objects.get_or_create(
        carrinho=carrinho,
        produto=produto,
        tamanho=tamanho,
    )

    if criado:
        item.quantidade = quantidade
    else:
        item.quantidade += quantidade
    item.save()
    carrinho.save(update_fields=['atualizado_em'])

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
def salvar_contato_carrinho(request):
    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return JsonResponse({'ok': False, 'erro': 'Carrinho nao encontrado.'}, status=404)

    carrinho = get_object_or_404(Carrinho, id=carrinho_id)
    carrinho.telefone_cliente = request.POST.get('telefone', '').strip()
    carrinho.aceita_whatsapp = bool(carrinho.telefone_cliente)
    carrinho.save(update_fields=['telefone_cliente', 'aceita_whatsapp', 'atualizado_em'])

    logger.info(
        '[CARRINHO] Contato salvo no carrinho %s. Aceita WhatsApp=%s',
        carrinho.id,
        carrinho.aceita_whatsapp,
    )
    return JsonResponse({'ok': True})


@require_POST
@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def aplicar_cupom_ajax(request):
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
        'desconto': float(desconto),
        'subtotal': float(subtotal),
    })


# ── CHECKOUT ───────────────────────────────────────────────────────
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
            # Mantem o frete selecionado quando o checkout volta com erro de validacao.
            'frete_valor_selecionado': frete_valor,
            'frete_nome_selecionado': frete_nome,
            'frete_service_id_selecionado': frete_service_id,
        }
        context.update(noindex_context(request, 'Checkout - Barrs Store'))
        return render(request, 'checkout.html', context)

    if request.method == 'POST':
        cliente = request.user if request.user.is_authenticated else None
        campos_obrigatorios = {
            'nome': 'Nome completo',
            'email': 'E-mail',
            'telefone': 'Celular',
            'cpf': 'CPF',
            'cep': 'CEP',
            'rua': 'Rua',
            'numero': 'Numero',
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

        if not request.user.is_authenticated:
            email_pedido = request.POST.get('email', '').strip().lower()
            senha = request.POST.get('senha', '').strip()

            if not senha:
                messages.error(request, 'Digite sua senha para entrar ou criar sua conta antes de finalizar.')
                return render_checkout()

            if len(senha) < 8:
                messages.error(request, 'A senha deve ter pelo menos 8 caracteres.')
                return render_checkout()

            usuario_existente = User.objects.filter(email__iexact=email_pedido).first()
            if usuario_existente:
                user = authenticate(request, username=usuario_existente.username, password=senha)
                if not user:
                    messages.error(request, 'Este e-mail ja tem cadastro. Digite a senha correta para continuar.')
                    return render_checkout()
                login(request, user)
                cliente = user
            else:
                nome_completo = request.POST.get('nome', '').strip()
                partes = nome_completo.split()
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
            desconto = cupom.calcular_desconto(subtotal)

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
    context = {
        'pedido': pedido,
        'mp_public_key': settings.MERCADOPAGO_PUBLIC_KEY,
    }
    context.update(noindex_context(request, f'Pedido #{pedido.id} - Barrs Store'))
    return render(request, 'confirmacao.html', context)


# ── MERCADO PAGO: CRIAR PREFERÊNCIA ───────────────────────────────
@require_POST
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
    telefone_limpo = "".join(filter(str.isdigit, pedido.telefone or ""))

    payer = {
        "name": pedido.nome,
        "email": pedido.email if pedido.email else "cliente@barrsstore.com.br",
    }
    if len(telefone_limpo) >= 10:
        payer["phone"] = {
            "area_code": telefone_limpo[:2],
            "number": telefone_limpo[2:],
        }

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
        "statement_descriptor": "BARRS STORE",
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response.get("response", {})
    if preference_response.get("status", 500) >= 400 or "id" not in preference:
        return JsonResponse({'erro': 'Nao foi possivel iniciar o pagamento.'}, status=502)

    return JsonResponse({
        "preference_id": preference["id"],
        "init_point": preference["init_point"],
    })


# ── MERCADO PAGO: RETORNOS ─────────────────────────────────────────
def pagamento_sucesso(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id and pedido.status != 'confirmado':
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento - Barrs Store'))
    return render(request, 'pagamento_sucesso.html', context)


def pagamento_falha(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento nao aprovado - Barrs Store'))
    return render(request, 'pagamento_falha.html', context)


def pagamento_pendente(request, pedido_id, token):
    pedido = get_pedido_por_token(pedido_id, token)
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id')
    if payment_id:
        confirmar_pagamento_mercadopago(payment_id)
        pedido.refresh_from_db()
    context = {'pedido': pedido}
    context.update(noindex_context(request, 'Pagamento pendente - Barrs Store'))
    return render(request, 'pagamento_pendente.html', context)


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
def cadastro(request):
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        email = request.POST.get('email', '').strip()
        senha = request.POST.get('senha', '')
        senha2 = request.POST.get('senha2', '')

        if senha != senha2:
            messages.error(request, 'As senhas não coincidem.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Este e-mail já está cadastrado.')
        elif len(senha) < 8:
            messages.error(request, 'A senha deve ter pelo menos 8 caracteres.')
        else:
            partes = nome.split()
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


def rastrear_pedido(request):
    pedido = None
    erro = ''
    if request.GET.get('pedido') or request.GET.get('email'):
        pedido_id = request.GET.get('pedido', '').strip().replace('#', '')
        email = request.GET.get('email', '').strip()
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
