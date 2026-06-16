import hashlib
import hmac as hmac_lib
import json
import logging
import os
import time

import requests as http_requests
from django.core.cache import cache

logger = logging.getLogger(__name__)


def _lalamove_headers(api_key: str, api_secret: str, method: str, path: str, body: str) -> dict:
    ts = str(int(time.time() * 1000))
    message = f"{ts}\r\n{method}\r\n{path}\r\n\r\n{body}"
    signature = hmac_lib.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return {
        'Authorization': f'hmac {api_key}:{ts}:{signature}',
        'Content-Type': 'application/json; charset=utf-8',
        'Market': 'BR',
    }


def _lalamove_config():
    from django.conf import settings as s
    api_key = getattr(s, 'LALAMOVE_API_KEY', '')
    api_secret = getattr(s, 'LALAMOVE_API_SECRET', '')
    sandbox = getattr(s, 'LALAMOVE_SANDBOX', True)
    if not api_key or not api_secret:
        raise RuntimeError('Lalamove não configurada: LALAMOVE_API_KEY ou LALAMOVE_API_SECRET ausentes.')
    base_url = 'https://rest.sandbox.lalamove.com' if sandbox else 'https://rest.lalamove.com'
    return api_key, api_secret, base_url


def is_sao_paulo_cep(cep: str) -> bool:
    cep = cep.replace('-', '').replace(' ', '')
    if len(cep) != 8 or not cep.isdigit():
        return False
    n = int(cep)
    return (1_000_000 <= n <= 5_999_999) or (8_000_000 <= n <= 8_499_999)


def cep_to_coordinates(cep: str) -> dict:
    cache_key = f'lalamove:coords:{cep}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    via_resp = http_requests.get(
        f'https://viacep.com.br/ws/{cep}/json/',
        timeout=5,
        headers={'User-Agent': 'BarrsStore contato.barrsstore@gmail.com'},
    )
    via_resp.raise_for_status()
    via_data = via_resp.json()

    if via_data.get('erro'):
        raise RuntimeError(f'CEP {cep} não encontrado no ViaCEP.')

    partes = [
        via_data.get('logradouro', ''),
        via_data.get('bairro', ''),
        via_data.get('localidade', ''),
        via_data.get('uf', ''),
        'Brasil',
    ]
    address = ', '.join(p for p in partes if p)

    nom_resp = http_requests.get(
        'https://nominatim.openstreetmap.org/search',
        params={'q': address, 'format': 'json', 'limit': 1, 'countrycodes': 'br'},
        timeout=8,
        headers={'User-Agent': 'BarrsStore contato.barrsstore@gmail.com'},
    )
    nom_resp.raise_for_status()
    nom_data = nom_resp.json()

    # Fallback: endereço completo não encontrado — tenta só cidade+estado
    if not nom_data:
        localidade = via_data.get('localidade', '')
        uf = via_data.get('uf', '')
        nom_resp2 = http_requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'city': localidade, 'state': uf, 'country': 'br', 'format': 'json', 'limit': 1},
            timeout=8,
            headers={'User-Agent': 'BarrsStore contato.barrsstore@gmail.com'},
        )
        nom_resp2.raise_for_status()
        nom_data = nom_resp2.json()

    if not nom_data:
        raise RuntimeError(f'Não foi possível geocodificar o CEP {cep}.')

    result = {
        'lat': nom_data[0]['lat'],
        'lng': nom_data[0]['lon'],   # Nominatim usa 'lon'; Lalamove espera 'lng'
        'address': address,
        'cep': cep,
    }
    cache.set(cache_key, result, 3600)
    return result


def _quotation_payload(origin: dict, destination: dict) -> str:
    payload = {
        'data': {
            'serviceType': 'LALAGO',
            'language': 'pt_BR',
            'stops': [
                {
                    'coordinates': {'lat': str(origin['lat']), 'lng': str(origin['lng'])},
                    'address': origin['address'],
                },
                {
                    'coordinates': {'lat': str(destination['lat']), 'lng': str(destination['lng'])},
                    'address': destination['address'],
                },
            ],
        }
    }
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False)


def get_lalamove_quotation(origin: dict, destination: dict) -> dict:
    api_key, api_secret, base_url = _lalamove_config()

    cache_key = f'lalamove:quote:{destination["cep"]}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    body = _quotation_payload(origin, destination)
    headers = _lalamove_headers(api_key, api_secret, 'POST', '/v3/quotations', body)

    logger.info('[Lalamove][DEBUG] REQUEST PAYLOAD: %s', json.dumps(json.loads(body), indent=2, ensure_ascii=False))

    resp = http_requests.post(
        f'{base_url}/v3/quotations',
        headers=headers,
        data=body.encode('utf-8'),
        timeout=10,
    )

    logger.info('[Lalamove][DEBUG] RESPONSE STATUS: %s', resp.status_code)
    logger.info('[Lalamove][DEBUG] RESPONSE BODY: %s', resp.text[:2000])
    try:
        logger.info('[Lalamove][DEBUG] RESPONSE JSON: %s', json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        pass

    if resp.status_code >= 400:
        logger.error('[Lalamove] Erro na cotação: %s %s', resp.status_code, resp.text[:300])
        raise RuntimeError(f'Lalamove retornou erro {resp.status_code}.')

    data = resp.json()['data']
    logger.info('[Lalamove][DEBUG] serviceType usado: %s', json.loads(body)['data'].get('serviceType'))
    logger.info('[Lalamove][DEBUG] priceBreakdown: %s', json.dumps(data.get('priceBreakdown', {}), indent=2, ensure_ascii=False))
    logger.info('[Lalamove][DEBUG] specialRequests: %s', data.get('specialRequests'))
    logger.info('[Lalamove][DEBUG] campos completos do data: %s', json.dumps({k: v for k, v in data.items() if k != 'stops'}, indent=2, ensure_ascii=False))
    result = {
        'price': float(data['priceBreakdown']['total']),
        'eta': 'Receba hoje',
        'quotation_id': data['quotationId'],
    }
    cache.set(cache_key, result, 600)
    return result


def create_lalamove_order(pedido) -> dict:
    """
    Faz cotação fresca e cria o pedido de entrega na Lalamove.
    Retorna {'order_id', 'tracking_url', 'quotation_id'}.
    Lança RuntimeError com mensagem legível em caso de falha.
    """
    from django.conf import settings as s

    api_key, api_secret, base_url = _lalamove_config()

    origin = {
        'lat': getattr(s, 'LALAMOVE_ORIGIN_LAT', ''),
        'lng': getattr(s, 'LALAMOVE_ORIGIN_LNG', ''),
        'address': getattr(s, 'LALAMOVE_ORIGIN_ADDRESS', ''),
    }
    if not origin['lat'] or not origin['lng']:
        raise RuntimeError('Coordenadas de origem não configuradas (LALAMOVE_ORIGIN_LAT/LNG).')

    dest = cep_to_coordinates(pedido.cep.replace('-', ''))

    # 1. Cotação fresca para obter quotationId + stopIds
    q_body = _quotation_payload(origin, dest)
    q_headers = _lalamove_headers(api_key, api_secret, 'POST', '/v3/quotations', q_body)

    logger.info('[Lalamove][DEBUG] create_order REQUEST PAYLOAD: %s', json.dumps(json.loads(q_body), indent=2, ensure_ascii=False))

    q_resp = http_requests.post(
        f'{base_url}/v3/quotations',
        headers=q_headers,
        data=q_body.encode('utf-8'),
        timeout=10,
    )

    logger.info('[Lalamove][DEBUG] create_order RESPONSE STATUS: %s', q_resp.status_code)
    logger.info('[Lalamove][DEBUG] create_order RESPONSE BODY: %s', q_resp.text[:2000])
    try:
        logger.info('[Lalamove][DEBUG] create_order RESPONSE JSON: %s', json.dumps(q_resp.json(), indent=2, ensure_ascii=False))
    except Exception:
        pass

    if q_resp.status_code >= 400:
        logger.error('[Lalamove] Cotação para pedido %s: %s %s', pedido.id, q_resp.status_code, q_resp.text[:300])
        raise RuntimeError(f'Lalamove cotação: erro {q_resp.status_code} — {q_resp.text[:120]}')

    q_data = q_resp.json()['data']
    quotation_id = q_data['quotationId']
    stops = q_data['stops']
    origin_stop_id = stops[0]['stopId']
    dest_stop_id = stops[1]['stopId']

    # 2. Criar pedido de entrega
    sender_phone = os.environ.get('ME_REMETENTE_TELEFONE', '11913225256').replace(' ', '').replace('-', '')
    recipient_phone = ''.join(c for c in (pedido.telefone or sender_phone) if c.isdigit())
    if not recipient_phone.startswith('55'):
        recipient_phone = '55' + recipient_phone

    order_payload = {
        'data': {
            'quotationId': quotation_id,
            'sender': {
                'stopId': origin_stop_id,
                'name': 'Barrs Store',
                'phone': f'+55{sender_phone}',
            },
            'recipients': [
                {
                    'stopId': dest_stop_id,
                    'name': pedido.nome,
                    'phone': f'+{recipient_phone}',
                    'remarks': pedido.complemento or '',
                }
            ],
            'isRecipientSMSEnabled': True,
            'isPODEnabled': False,
        }
    }

    o_body = json.dumps(order_payload, separators=(',', ':'), ensure_ascii=False)
    o_headers = _lalamove_headers(api_key, api_secret, 'POST', '/v3/orders', o_body)
    o_resp = http_requests.post(
        f'{base_url}/v3/orders',
        headers=o_headers,
        data=o_body.encode('utf-8'),
        timeout=15,
    )
    if o_resp.status_code >= 400:
        logger.error('[Lalamove] Criar pedido %s: %s %s', pedido.id, o_resp.status_code, o_resp.text[:300])
        raise RuntimeError(f'Lalamove criar pedido: erro {o_resp.status_code} — {o_resp.text[:120]}')

    o_data = o_resp.json()['data']
    return {
        'order_id': o_data['orderId'],
        'tracking_url': o_data.get('shareLink', ''),
        'quotation_id': quotation_id,
    }
