import hashlib
import hmac as hmac_lib
import json
import logging
import time

import requests as http_requests
from django.core.cache import cache

logger = logging.getLogger(__name__)


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


def get_lalamove_quotation(origin: dict, destination: dict) -> dict:
    from django.conf import settings as django_settings

    api_key = getattr(django_settings, 'LALAMOVE_API_KEY', '')
    api_secret = getattr(django_settings, 'LALAMOVE_API_SECRET', '')
    sandbox = getattr(django_settings, 'LALAMOVE_SANDBOX', True)

    if not api_key or not api_secret:
        raise RuntimeError('Lalamove não configurada: LALAMOVE_API_KEY ou LALAMOVE_API_SECRET ausentes.')

    cache_key = f'lalamove:quote:{destination["cep"]}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    base_url = 'https://rest.sandbox.lalamove.com' if sandbox else 'https://rest.lalamove.com'

    payload = {
        'data': {
            'serviceType': 'MOTORCYCLE',
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

    ts = str(int(time.time() * 1000))
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    message = f"{ts}\r\nPOST\r\n/v3/quotations\r\n\r\n{body}"
    signature = hmac_lib.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        'Authorization': f'hmac {api_key}:{ts}:{signature}',
        'Content-Type': 'application/json; charset=utf-8',
        'Market': 'BR',
    }

    resp = http_requests.post(
        f'{base_url}/v3/quotations',
        headers=headers,
        data=body.encode('utf-8'),
        timeout=10,
    )

    if resp.status_code >= 400:
        logger.error('[Lalamove] Erro na cotação: %s %s', resp.status_code, resp.text[:300])
        raise RuntimeError(f'Lalamove retornou erro {resp.status_code}.')

    data = resp.json()
    price_str = data['data']['priceBreakdown']['total']
    quotation_id = data['data']['quotationId']

    result = {
        'price': float(price_str),
        'eta': '30-45 min',
        'quotation_id': quotation_id,
    }
    cache.set(cache_key, result, 600)
    return result
