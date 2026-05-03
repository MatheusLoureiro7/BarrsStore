import logging
import re

import requests
from django.conf import settings


logger = logging.getLogger(__name__)


def formatar_numero_brasil(numero):
    digitos = re.sub(r'\D', '', numero or '')
    if not digitos:
        return ''
    if digitos.startswith('55') and len(digitos) >= 12:
        return digitos
    if len(digitos) == 10 and digitos[2] == '9':
        digitos = f'{digitos[:2]}9{digitos[2:]}'
    if len(digitos) in (10, 11):
        return f'55{digitos}'
    return digitos


def enviar_whatsapp(numero, mensagem):
    api_url = getattr(settings, 'WHATSAPP_API_URL', '').rstrip('/')
    api_key = getattr(settings, 'WHATSAPP_API_KEY', '')
    instance = getattr(settings, 'WHATSAPP_INSTANCE', 'loja') or 'loja'
    numero_formatado = formatar_numero_brasil(numero)

    if not api_url or not api_key:
        logger.warning('[WHATSAPP] API nao configurada. Configure WHATSAPP_API_URL e WHATSAPP_API_KEY.')
        return {
            'ok': False,
            'numero': numero_formatado,
            'status_code': None,
            'body': 'API nao configurada.',
        }

    if not numero_formatado:
        logger.info('[WHATSAPP] Envio ignorado: numero vazio.')
        return {
            'ok': False,
            'numero': numero_formatado,
            'status_code': None,
            'body': 'Numero vazio.',
        }

    endpoint = f'{api_url}/message/sendText/{instance}'
    try:
        resposta = requests.post(
            endpoint,
            headers={
                'apikey': api_key,
                'Content-Type': 'application/json',
            },
            json={
                'number': numero_formatado,
                'text': mensagem,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.exception('[WHATSAPP] Falha de conexao ao enviar para %s: %s', numero_formatado, exc)
        return {
            'ok': False,
            'numero': numero_formatado,
            'status_code': None,
            'body': str(exc),
        }

    if 200 <= resposta.status_code < 300:
        logger.info(
            '[WHATSAPP] Mensagem enviada para %s. Status %s: %s',
            numero_formatado,
            resposta.status_code,
            resposta.text[:500],
        )
        return {
            'ok': True,
            'numero': numero_formatado,
            'status_code': resposta.status_code,
            'body': resposta.text[:500],
        }

    logger.error(
        '[WHATSAPP] API recusou mensagem para %s. Status %s: %s',
        numero_formatado,
        resposta.status_code,
        resposta.text[:500],
    )
    return {
        'ok': False,
        'numero': numero_formatado,
        'status_code': resposta.status_code,
        'body': resposta.text[:500],
    }
