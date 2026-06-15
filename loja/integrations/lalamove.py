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
