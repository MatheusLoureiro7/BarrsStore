import logging
import os
from decimal import Decimal

import requests as http_requests
from django.conf import settings

from ..integrations.lalamove import is_sao_paulo_cep, cep_to_coordinates, get_lalamove_quotation
from ..shipping import calcular_frete_por_estado  # noqa: F401 — re-exportado
from .utils import (
    apenas_digitos,
    resposta_externa_segura_para_log,
    ratelimit,
    site_url,
)
from .emails import enviar_whatsapp_alerta_melhor_envio

logger = logging.getLogger(__name__)

CAIXA_ENVIO = {
    'width': 11,
    'length': 16,
    'height': 6,
    'weight': 0.5,
}

# Peso realista de semijoias: 60g de embalagem + peso unitario por peca.
# Quando o produto nao tem peso_gramas cadastrado, assumimos 8g por item.
PESO_EMBALAGEM_GRAMAS = 60
PESO_PADRAO_ITEM_GRAMAS = 8


def _peso_unitario_gramas(produto):
    """Peso em gramas de uma unidade do produto, com fallback seguro."""
    peso = getattr(produto, 'peso_gramas', None) if produto is not None else None
    try:
        peso = int(peso) if peso else 0
    except (TypeError, ValueError):
        peso = 0
    return peso if peso > 0 else PESO_PADRAO_ITEM_GRAMAS


def calcular_peso_envio_kg(itens):
    """Peso total do envio em kg: embalagem fixa + soma dos pesos dos itens."""
    peso_total_g = PESO_EMBALAGEM_GRAMAS
    for item in itens or []:
        try:
            quantidade = int(getattr(item, 'quantidade', 0) or 0)
        except (TypeError, ValueError):
            quantidade = 0
        if quantidade <= 0:
            continue
        peso_total_g += _peso_unitario_gramas(getattr(item, 'produto', None)) * quantidade
    return round(peso_total_g / 1000, 3)


def pacote_envio_por_quantidade(total_itens, peso_kg=None):
    """Ajusta peso e altura da caixa sem alterar a embalagem padrao da loja.

    Quando `peso_kg` nao e informado, usa o fallback 60g embalagem + 8g por item.
    """
    total_itens = max(int(total_itens or 1), 1)
    if peso_kg is None or peso_kg <= 0:
        peso_kg = round(
            (PESO_EMBALAGEM_GRAMAS + PESO_PADRAO_ITEM_GRAMAS * total_itens) / 1000,
            3,
        )
    altura_extra = max(total_itens - 1, 0) // 4
    return {
        'width': CAIXA_ENVIO['width'],
        'length': CAIXA_ENVIO['length'],
        'height': min(CAIXA_ENVIO['height'] + altura_extra, 18),
        'weight': float(peso_kg),
    }


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
    itens_pedido = list(pedido.itens.select_related('produto').all())
    pacote = pacote_envio_por_quantidade(
        sum(item.quantidade for item in itens_pedido),
        peso_kg=calcular_peso_envio_kg(itens_pedido),
    )

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
            enviar_whatsapp_alerta_melhor_envio(pedido, texto)
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
        enviar_whatsapp_alerta_melhor_envio(pedido, str(exc))
        return False


# ── CALCULAR FRETE VIA MELHOR ENVIO ───────────────────────────────
@ratelimit(key='ip', rate='30/m', method='GET', block=True)
def calcular_frete_melhor_envio(request):
    """Calcula frete real via API do Melhor Envio pelo CEP."""
    from decimal import Decimal
    from django.http import JsonResponse
    from ..models import Carrinho

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
            itens_carrinho = list(carrinho.itens.select_related('produto').all())
            total_itens = sum(item.quantidade for item in itens_carrinho)
            pacote = pacote_envio_por_quantidade(
                total_itens,
                peso_kg=calcular_peso_envio_kg(itens_carrinho),
            )
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

        if is_sao_paulo_cep(cep_destino):
            try:
                dest = cep_to_coordinates(cep_destino)
                origin = {
                    'lat': settings.LALAMOVE_ORIGIN_LAT,
                    'lng': settings.LALAMOVE_ORIGIN_LNG,
                    'address': settings.LALAMOVE_ORIGIN_ADDRESS,
                }
                lala = get_lalamove_quotation(origin, dest)
                opcoes.insert(0, {
                    'id': 'lalamove-moto',
                    'nome': 'Motoboy · Entrega no mesmo dia',
                    'empresa': 'Lalamove',
                    'preco': lala['price'],
                    'prazo': 0,
                    'eta': lala['eta'],
                    'quotation_id': lala['quotation_id'],
                })
            except Exception:
                logger.warning('[Lalamove] Falha ao cotar CEP %s', cep_destino)

        return JsonResponse({'opcoes': opcoes})

    except Exception:
        logger.exception('[ME] Falha ao calcular frete cep=%s', cep_destino)
        return JsonResponse({'erro': 'Nao foi possivel calcular o frete agora.'}, status=500)
