import hashlib
import hmac
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)


def _parse_signature_header(signature_header):
    partes = {}
    for parte in (signature_header or '').split(','):
        if '=' not in parte:
            continue
        chave, valor = parte.split('=', 1)
        partes[chave.strip()] = valor.strip()
    return partes.get('ts'), partes.get('v1')


def _timestamp_fresco(ts):
    try:
        timestamp = int(ts)
    except (TypeError, ValueError):
        return False

    # Mercado Pago documenta ts em milissegundos; o fallback em segundos evita falso negativo em integrações antigas.
    if timestamp < 10_000_000_000:
        timestamp *= 1000
    agora_ms = int(time.time() * 1000)
    tolerancia_ms = getattr(settings, 'MERCADOPAGO_WEBHOOK_TOLERANCE_SECONDS', 600) * 1000
    return abs(agora_ms - timestamp) <= tolerancia_ms


def validar_assinatura_mercadopago(request, data):
    secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
    if not secret:
        # O webhook apenas dispara uma consulta autenticada na API do Mercado Pago usando nosso access token.
        # Se o segredo ainda nao foi configurado no Railway, aceitamos o aviso para nao travar confirmacoes reais.
        # Em producao, configure MP_WEBHOOK_SECRET para ativar a validacao HMAC estrita.
        logger.warning('MERCADOPAGO_WEBHOOK_SECRET ausente. Webhook aceito em modo compatibilidade.')
        return True, 'sem_secret_modo_compatibilidade'

    signature_header = request.headers.get('x-signature', '')
    request_id = request.headers.get('x-request-id', '')
    ts, assinatura = _parse_signature_header(signature_header)

    if not ts or not assinatura:
        return False, 'assinatura_ausente'
    if not _timestamp_fresco(ts):
        return False, 'timestamp_expirado'

    data_id = (
        request.GET.get('data.id')
        or request.GET.get('id')
        or str((data.get('data') or {}).get('id') or '')
    )
    data_id = data_id.lower() if data_id and not data_id.isdigit() else data_id

    manifesto = ''
    if data_id:
        manifesto += f'id:{data_id};'
    if request_id:
        manifesto += f'request-id:{request_id};'
    manifesto += f'ts:{ts};'

    esperado = hmac.new(secret.encode('utf-8'), manifesto.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, assinatura):
        return False, 'assinatura_invalida'
    return True, 'ok'
