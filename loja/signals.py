import logging

import requests
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Pedido

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Pedido)
def notificar_erp_nova_venda(sender, instance, created, update_fields, **kwargs):
    if created:
        return
    if update_fields is not None and 'status' not in update_fields:
        return
    if instance.status != 'confirmado':
        return
    _chamar_webhook_erp(instance.id)


def _chamar_webhook_erp(pedido_id):
    url = getattr(settings, 'ERP_WEBHOOK_URL', '')
    token = getattr(settings, 'ERP_WEBHOOK_TOKEN', '')
    if not url or not token:
        return
    try:
        requests.post(
            url,
            json={'pedido_id': pedido_id},
            headers={'X-Webhook-Token': token},
            timeout=5,
        )
    except Exception as exc:
        logger.warning('ERP webhook falhou para pedido %s: %s', pedido_id, exc)
