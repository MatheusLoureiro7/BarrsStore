import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import Pedido
from loja.views import enviar_email_pagamento_pendente

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Envia o e-mail "Finalize seu pagamento" para pedidos pendentes criados '
        'ha mais de N minutos (padrao 20) e que ainda nao receberam o e-mail. '
        'Evita disparo imediato no checkout (que parecia SPAM para quem fecha logo).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--min-idade-minutos', type=int, default=20,
            help='So envia para pedidos com pelo menos N minutos. Padrao: 20.',
        )
        parser.add_argument(
            '--max-idade-horas', type=int, default=24,
            help='Nao envia para pedidos antigos demais. Padrao: 24h.',
        )
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        agora = timezone.now()
        limite_jovem = agora - timedelta(minutes=options['min_idade_minutos'])
        limite_velho = agora - timedelta(hours=options['max_idade_horas'])
        dry = options['dry_run']

        pedidos = Pedido.objects.filter(
            status='pendente',
            email_pagamento_pendente_enviado=False,
            criado_em__lte=limite_jovem,
            criado_em__gte=limite_velho,
        ).order_by('criado_em')

        total = pedidos.count()
        if total == 0:
            self.stdout.write('Nenhum pedido pendente elegivel encontrado.')
            return

        if dry:
            self.stdout.write(f'[DRY-RUN] Enviaria e-mail para {total} pedido(s) pendente(s).')
            return

        enviados = 0
        falhas = 0
        for pedido in pedidos:
            try:
                if enviar_email_pagamento_pendente(pedido):
                    enviados += 1
                else:
                    falhas += 1
            except Exception as exc:
                logger.exception('Falha ao enviar e-mail de pagamento pendente do pedido %s: %s', pedido.id, exc)
                falhas += 1

        self.stdout.write(self.style.SUCCESS(
            f'E-mails de pagamento pendente enviados: {enviados}. Falhas: {falhas}.'
        ))
