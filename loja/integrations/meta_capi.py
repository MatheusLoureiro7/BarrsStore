import hashlib
import logging
import time
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def safe_payload_for_log(payload):
    """Copia o payload para log sem expor o access_token."""
    safe_payload = dict(payload)
    if 'access_token' in safe_payload:
        safe_payload['access_token'] = '***'
    return safe_payload


def normalize_and_hash(value):
    """Normaliza dados pessoais antes do SHA256 exigido pela Meta CAPI."""
    if not value:
        return ''
    normalized = str(value).strip().lower()
    if not normalized:
        return ''
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def only_digits(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def hash_phone_br(value):
    digits = only_digits(value)
    if not digits:
        return ''
    if not digits.startswith('55') and len(digits) in (10, 11):
        digits = f'55{digits}'
    return normalize_and_hash(digits)


def order_success_url(pedido):
    try:
        path = reverse('pagamento_sucesso', kwargs={
            'pedido_id': pedido.id,
            'token': pedido.access_token,
        })
    except Exception:
        path = f'/pagamento/sucesso/{pedido.id}/'
    base = getattr(settings, 'SITE_URL', 'https://www.barrsstore.com.br').rstrip('/')
    return f'{base}{path}'


def send_purchase_event(pedido):
    """Envia Purchase para Meta Conversions API sem expor token no frontend."""
    pixel_id = getattr(settings, 'META_PIXEL_ID', '').strip()
    access_token = getattr(settings, 'META_ACCESS_TOKEN', '').strip()
    test_event_code = getattr(settings, 'META_TEST_EVENT_CODE', '').strip()

    if not pixel_id or not access_token:
        logger.info('[META CAPI] Pixel/token nao configurados. Pedido %s ignorado.', pedido.id)
        return False

    event_id = f'purchase_{pedido.id}'
    content_ids = [str(item.produto_id) for item in pedido.itens.all() if item.produto_id]

    user_data = {}
    email_hash = normalize_and_hash(pedido.email)
    phone_hash = hash_phone_br(pedido.telefone)
    if email_hash:
        user_data['em'] = [email_hash]
    if phone_hash:
        user_data['ph'] = [phone_hash]

    value = pedido.total if isinstance(pedido.total, Decimal) else Decimal(str(pedido.total or '0'))
    custom_data = {
        'currency': 'BRL',
        'value': float(value),
        'order_id': str(pedido.id),
        'content_ids': content_ids,
        'content_type': 'product',
    }
    # Inclui UTM/gclid/fbclid no custom_data para atribuicao server-side no Meta.
    utm = getattr(pedido, 'origem_utm', None) or {}
    for chave in ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'):
        if utm.get(chave):
            custom_data[chave] = utm[chave]
    fbc = utm.get('fbclid')
    if fbc:
        user_data['fbc'] = f'fb.1.{int(time.time())}.{fbc}'

    payload = {
        'data': [
            {
                'event_name': 'Purchase',
                'event_time': int(time.time()),
                'event_id': event_id,
                'action_source': 'website',
                'event_source_url': order_success_url(pedido),
                'user_data': user_data,
                'custom_data': custom_data,
            }
        ],
        'access_token': access_token,
    }
    if test_event_code:
        payload['test_event_code'] = test_event_code

    url = f'https://graph.facebook.com/v22.0/{pixel_id}/events'
    logger.info('[META CAPI] Preparando Purchase pedido=%s event_id=%s teste=%s', pedido.id, event_id, bool(test_event_code))
    logger.info('[META CAPI] Payload pedido=%s: %s', pedido.id, safe_payload_for_log(payload))
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code >= 400:
            logger.warning(
                '[META CAPI] Falha ao enviar Purchase pedido=%s status=%s resposta=%s',
                pedido.id,
                response.status_code,
                response.text[:500],
            )
            return False
        logger.info('[META CAPI] Purchase enviado pedido=%s event_id=%s status=%s', pedido.id, event_id, response.status_code)
        logger.info('[META CAPI] Resposta Meta pedido=%s: %s', pedido.id, response.text[:500])
        return True
    except requests.RequestException as exc:
        logger.warning('[META CAPI] Erro ao enviar Purchase pedido=%s: %s', pedido.id, exc)
        return False