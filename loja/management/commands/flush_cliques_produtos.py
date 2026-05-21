import logging

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models import F

from loja.models import Produto

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Consolida os contadores de cliques bufferizados no cache (chave cliques:<id>) '
        'no campo Produto.cliques. Reduz UPDATEs no DB de N (1 por visita) para 1 por '
        'execucao deste cron. Agendar a cada 5-10 minutos.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        pendentes = cache.get('cliques:pendentes') or set()
        if not pendentes:
            self.stdout.write('Nenhum clique pendente para consolidar.')
            return

        dry = options['dry_run']
        total_persistidos = 0
        produtos_atualizados = 0

        for produto_id in list(pendentes):
            key = f'cliques:{produto_id}'
            count = cache.get(key) or 0
            if count <= 0:
                continue
            if dry:
                self.stdout.write(f'[DRY-RUN] Produto {produto_id}: +{count} cliques')
                total_persistidos += count
                produtos_atualizados += 1
                continue
            updated = Produto.objects.filter(pk=produto_id).update(cliques=F('cliques') + count)
            if updated:
                # Reduz o contador no cache pelo numero ja persistido. Cliques que
                # cheguem entre o get acima e o decr abaixo continuam contabilizados.
                try:
                    cache.decr(key, count)
                except ValueError:
                    cache.delete(key)
                total_persistidos += count
                produtos_atualizados += 1
            else:
                # Produto removido: limpa cache para nao acumular.
                cache.delete(key)

        if not dry:
            cache.delete('cliques:pendentes')

        prefix = '[DRY-RUN] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{produtos_atualizados} produto(s) atualizados, {total_persistidos} clique(s) consolidados.'
        ))
        logger.info('[CLIQUES] Flush concluido: %s produtos, %s cliques.', produtos_atualizados, total_persistidos)
