import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import Pedido
from loja.views import (
    enviar_email_poscompra_1,
    enviar_email_poscompra_2,
    enviar_email_poscompra_3,
    enviar_email_poscompra_4,
    enviar_email_poscompra_5,
)

logger = logging.getLogger(__name__)

# (flag, função, janela_min_horas, janela_max_horas)
SEQUENCIA = [
    ('email_poscompra_1_enviado', enviar_email_poscompra_1, 0.5, 4),
    ('email_poscompra_2_enviado', enviar_email_poscompra_2, 22, 26),
    ('email_poscompra_3_enviado', enviar_email_poscompra_3, 60, 84),
    ('email_poscompra_4_enviado', enviar_email_poscompra_4, 144, 192),
    ('email_poscompra_5_enviado', enviar_email_poscompra_5, 336, 384),
]


class Command(BaseCommand):
    help = 'Envia sequência premium de e-mails pós-compra para pedidos confirmados.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Mostra o que seria enviado sem chamar a API.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        agora = timezone.now()
        total_enviados = 0

        for flag, funcao, horas_min, horas_max in SEQUENCIA:
            janela_inicio = agora - timedelta(hours=horas_max)
            janela_fim = agora - timedelta(hours=horas_min)

            pedidos = (
                Pedido.objects
                .filter(
                    status='confirmado',
                    criado_em__gte=janela_inicio,
                    criado_em__lte=janela_fim,
                    **{flag: False},
                )
                .prefetch_related('itens')
            )

            count = pedidos.count()
            if not count:
                continue

            self.stdout.write(f'[POSCOMPRA] {flag}: {count} pedido(s) elegível(is)')

            for pedido in pedidos:
                if dry_run:
                    self.stdout.write(f'  [DRY-RUN] Pedido {pedido.id} → {pedido.email}')
                    continue

                ok = funcao(pedido)
                status = 'OK' if ok else 'FALHOU'
                self.stdout.write(f'  Pedido {pedido.id} → {status}')
                if ok:
                    total_enviados += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f'[POSCOMPRA] Total enviados: {total_enviados}'))
