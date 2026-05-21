import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import EmailPendente

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Apaga EmailPendente com status=enviado mais antigos que N dias (padrão 90). Mantém status=pendente e status=erro intactos.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=90,
                            help='Idade mínima em dias para apagar. Padrão: 90.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostra quantos seriam apagados sem deletar.')

    def handle(self, *args, **options):
        dias = options['dias']
        dry_run = options['dry_run']
        limite = timezone.now() - timedelta(days=dias)

        queryset = EmailPendente.objects.filter(status='enviado', enviado_em__lt=limite)
        total = queryset.count()

        if dry_run:
            self.stdout.write(f'[DRY-RUN] Apagaria {total} EmailPendente com status=enviado e enviado_em < {limite.isoformat()}')
            return

        if total == 0:
            self.stdout.write('Nenhum registro para apagar.')
            return

        queryset.delete()
        logger.info('[EMAIL-CLEANUP] %s registros apagados (status=enviado, >%sd).', total, dias)
        self.stdout.write(self.style.SUCCESS(f'{total} EmailPendente apagados.'))
