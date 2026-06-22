import hashlib
import logging
import threading
import time
from decimal import Decimal

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def mask_meta_value(value):
    if value is None:
        return None
    text = str(value)
    if not text:
        return ''
    if len(text) <= 10:
        return f'{text[:2]}***'
    return f'{text[:6]}...{text[-4:]}'


def mask_user_data(user_data):
    masked = {}
    for key, value in (user_data or {}).items():
        if isinstance(value, list):
            masked[key] = [mask_meta_value(item) for item in value]
        else:
            masked[key] = mask_meta_value(value)
    return masked


def safe_payload_for_log(payload):
    """Copia o payload para log sem expor o access_token."""
    safe_payload = dict(payload)
    if 'access_token' in safe_payload:
        safe_payload['access_token'] = '***'
    data = []
    for item in safe_payload.get('data', []):
        safe_item = dict(item)
        safe_item['user_data'] = mask_user_data(safe_item.get('user_data', {}))
        data.append(safe_item)
    if data:
        safe_payload['data'] = data
    return safe_payload


def response_json_for_log(response):
    try:
        return response.json()
    except ValueError:
        return None


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


def _post_capi(event_name, event_id, source_url, user_data, custom_data):
    """Helper interno: envia 1 evento para a Meta Conversions API. Nunca propaga erro."""
    pixel_id = getattr(settings, 'META_PIXEL_ID', '').strip()
    access_token = getattr(settings, 'META_ACCESS_TOKEN', '').strip()
    test_event_code = getattr(settings, 'META_TEST_EVENT_CODE', '').strip()
    if not pixel_id or not access_token:
        logger.warning(
            '[META CAPI] %s CONFIG INCOMPLETA pixel_id=%s access_token_present=%s test_event_code=%s',
            event_name,
            pixel_id or '',
            bool(access_token),
            test_event_code or '',
        )
        return False

    payload = {
        'data': [
            {
                'event_name': event_name,
                'event_time': int(time.time()),
                'event_id': event_id,
                'action_source': 'website',
                'event_source_url': source_url,
                'user_data': user_data,
                'custom_data': custom_data,
            }
        ],
        'access_token': access_token,
    }
    if test_event_code:
        payload['test_event_code'] = test_event_code

    url = f'https://graph.facebook.com/v22.0/{pixel_id}/events'
    logger.info(
        '[META EVENT ID] %s capi=%s',
        event_name,
        event_id,
    )
    logger.info(
        '[META CAPI] %s PREPARANDO event_id=%s pixel_id=%s test_event_code=%s event_source_url=%s custom_data=%s user_data=%s payload=%s',
        event_name,
        event_id,
        pixel_id,
        test_event_code or '',
        source_url,
        custom_data,
        mask_user_data(user_data),
        safe_payload_for_log(payload),
    )
    try:
        response = requests.post(url, json=payload, timeout=8)
        response_json = response_json_for_log(response)
        logger.info(
            '[META CAPI] %s RESPOSTA status=%s response=%s response_json=%s',
            event_name,
            response.status_code,
            response.text,
            response_json,
        )
        if response.status_code >= 400:
            logger.warning('[META CAPI] %s falhou status=%s resposta=%s',
                           event_name, response.status_code, response.text[:300])
            return False
        logger.info('[META CAPI] %s enviado event_id=%s', event_name, event_id)
        return True
    except requests.RequestException as exc:
        logger.warning('[META CAPI] Erro %s event_id=%s: %s', event_name, event_id, exc)
        return False


def _post_capi_async(event_name, event_id, source_url, user_data, custom_data):
    """Dispara _post_capi numa thread daemon: nao bloqueia a resposta ao usuario.

    Use para eventos no caminho critico de UX (ex: AddToCart), onde segurar a
    resposta ate a Meta responder degradaria a experiencia. O user_data/source_url
    ja devem ter sido extraidos do request ANTES de chamar (a thread nao acessa o
    request, que pode estar fechado depois que a resposta e enviada).
    """
    thread = threading.Thread(
        target=_post_capi,
        args=(event_name, event_id, source_url, user_data, custom_data),
        name=f'capi-{event_name}',
        daemon=True,
    )
    thread.start()
    return True


def _user_data_from_request(request):
    """Monta user_data a partir da sessao/cookies para AddToCart/InitiateCheckout.

    Sem PII obrigatoria (usuario nao logado), mas inclui IP, user-agent e
    fbp/fbc se disponiveis para o Meta tentar identificar o visitante.
    """
    ud = {}
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
    if ip:
        ud['client_ip_address'] = ip
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    if user_agent:
        ud['client_user_agent'] = user_agent[:500]
    fbp = request.COOKIES.get('_fbp')
    if fbp:
        ud['fbp'] = fbp
    fbc = request.COOKIES.get('_fbc')
    if fbc:
        ud['fbc'] = fbc
    # Se Meta deu fbclid recente, sintetiza fbc no formato oficial.
    utm = (request.session.get('utm') or {}) if hasattr(request, 'session') else {}
    if not fbc and utm.get('fbclid'):
        ud['fbc'] = f'fb.1.{int(time.time())}.{utm["fbclid"]}'
    # Email do usuario logado tambem ajuda matching.
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False) and getattr(user, 'email', ''):
        email_hash = normalize_and_hash(user.email)
        if email_hash:
            ud['em'] = [email_hash]
    return ud


def send_add_to_cart_event(produto, request, event_id):
    """AddToCart server-side. Use o MESMO event_id do Pixel para dedupe."""
    value = produto.preco if isinstance(produto.preco, Decimal) else Decimal(str(produto.preco or '0'))
    custom = {
        'content_ids': [str(produto.id)],
        'content_type': 'product',
        'content_name': produto.nome,
        'value': float(value),
        'currency': 'BRL',
    }
    source_url = request.build_absolute_uri(produto.get_absolute_url())
    # user_data extraido do request AQUI (thread principal); a thread so faz o HTTP.
    user_data = _user_data_from_request(request)
    return _post_capi_async('AddToCart', event_id, source_url, user_data, custom)


def send_initiate_checkout_event(carrinho, request, event_id):
    """InitiateCheckout server-side. Use o MESMO event_id do Pixel para dedupe."""
    itens = list(carrinho.itens.select_related('produto').all())
    content_ids = [str(item.produto_id) for item in itens if item.produto_id]
    total = sum((item.subtotal() for item in itens), Decimal('0'))
    custom = {
        'content_ids': content_ids,
        'content_type': 'product',
        'value': float(total),
        'currency': 'BRL',
        'num_items': sum(item.quantidade for item in itens),
    }
    source_url = request.build_absolute_uri(reverse('finalizar_compra'))
    return _post_capi('InitiateCheckout', event_id, source_url, _user_data_from_request(request), custom)


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
    # fbc: preferir valor direto do cookie _fbc; cair para fbclid se disponivel.
    fbc_cookie = utm.get('fbc', '')
    fbc_fbclid = utm.get('fbclid', '')
    if fbc_cookie:
        user_data['fbc'] = fbc_cookie
    elif fbc_fbclid:
        user_data['fbc'] = f'fb.1.{int(time.time())}.{fbc_fbclid}'
    # fbp: identificador do navegador do cookie _fbp.
    fbp_val = utm.get('fbp', '')
    if fbp_val:
        user_data['fbp'] = fbp_val
    # IP e user-agent: aumentam significativamente o Event Match Quality na CAPI.
    client_ip = utm.get('client_ip_address', '')
    if client_ip:
        user_data['client_ip_address'] = client_ip
    client_ua = utm.get('client_user_agent', '')
    if client_ua:
        user_data['client_user_agent'] = client_ua

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
    logger.info('[META EVENT ID] Purchase frontend=%s backend=%s capi=%s', event_id, event_id, event_id)
    logger.info(
        '[META CAPI] Purchase PREPARANDO pedido=%s event_id=%s pixel_id=%s test_event_code=%s event_source_url=%s custom_data=%s user_data=%s payload=%s',
        pedido.id,
        event_id,
        pixel_id,
        test_event_code or '',
        order_success_url(pedido),
        custom_data,
        mask_user_data(user_data),
        safe_payload_for_log(payload),
    )
    logger.info('[META CAPI] Preparando Purchase pedido=%s event_id=%s teste=%s', pedido.id, event_id, bool(test_event_code))
    logger.info('[META CAPI] Payload pedido=%s: %s', pedido.id, safe_payload_for_log(payload))
    try:
        response = requests.post(url, json=payload, timeout=10)
        response_json = response_json_for_log(response)
        logger.info(
            '[META CAPI] Purchase RESPOSTA pedido=%s status=%s response=%s response_json=%s',
            pedido.id,
            response.status_code,
            response.text,
            response_json,
        )
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
