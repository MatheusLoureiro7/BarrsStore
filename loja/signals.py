import logging

import requests
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Pedido

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Pedido)
def notificar_erp_nova_venda(sender, instance, created, update_fields, **kwargs):
    logger.debug(
        'post_save Pedido #%s | created=%s | status=%s | update_fields=%s',
        instance.id, created, instance.status, update_fields,
    )
    if created:
        return
    if update_fields is not None and 'status' not in update_fields:
        return
    if instance.status != 'confirmado':
        return
    logger.info('Pedido #%s confirmado — disparando webhook ERP', instance.id)
    _chamar_webhook_erp(instance.id)


def _chamar_webhook_erp(pedido_id):
    url = getattr(settings, 'ERP_WEBHOOK_URL', '').strip()
    token = getattr(settings, 'ERP_WEBHOOK_TOKEN', '').strip()
    if not url:
        logger.warning('ERP webhook não chamado: ERP_WEBHOOK_URL não configurado (pedido %s)', pedido_id)
        return
    if not token:
        logger.warning('ERP webhook não chamado: ERP_WEBHOOK_TOKEN não configurado (pedido %s)', pedido_id)
        return
    logger.info('Chamando ERP webhook %s para pedido %s', url, pedido_id)
    try:
        resp = requests.post(
            url,
            json={'pedido_id': pedido_id},
            headers={'X-Webhook-Token': token},
            timeout=5,
        )
        logger.info('ERP webhook respondeu %s para pedido %s', resp.status_code, pedido_id)
    except Exception as exc:
        logger.warning('ERP webhook falhou para pedido %s: %s', pedido_id, exc)
