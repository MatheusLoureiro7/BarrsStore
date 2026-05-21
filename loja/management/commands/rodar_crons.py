import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Orquestrador de crons da loja. Roda a cada 5 minutos no Railway. '
        'Decide internamente quais sub-commands executar conforme o horario, '
        'evitando a necessidade de configurar varios crons separados.\n\n'
        'Agendamento no Railway:  */5 * * * *  python manage.py rodar_crons'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostra o que rodaria sem executar.')
        parser.add_argument('--forcar', action='store_true',
                            help='Ignora janelas de tempo e roda TODOS os sub-commands (uso manual).')

    def handle(self, *args, **options):
        agora = timezone.localtime()
        minuto = agora.minute
        hora = agora.hour
        dry = options['dry_run']
        forcar = options['forcar']

        # Lista de (condicao_deve_rodar, nome_amigavel, command_args).
        tarefas = [
            (
                True,  # toda execucao (a cada 5min)
                'flush_cliques_produtos',
                ('flush_cliques_produtos', []),
            ),
            (
                minuto % 15 == 0,
                'enviar_emails_pendentes',
                ('enviar_emails_pendentes', []),
            ),
            (
                minuto % 15 == 0,
                'enviar_emails_pagamento_pendente',
                ('enviar_emails_pagamento_pendente', []),
            ),
            (
                minuto % 30 == 0,
                'enviar_poscompra',
                ('enviar_poscompra', []),
            ),
            (
                minuto % 30 == 0,
                'enviar_carrinhos_abandonados',
                ('enviar_carrinhos_abandonados', []),
            ),
            (
                hora == 3 and minuto < 5,
                'limpar_emails_antigos',
                ('limpar_emails_antigos', []),
            ),
        ]

        executadas = 0
        falhas = 0

        for deve_rodar, nome, (cmd, cmd_args) in tarefas:
            if not (deve_rodar or forcar):
                continue

            if dry:
                self.stdout.write(f'[DRY-RUN] Rodaria: {nome}')
                executadas += 1
                continue

            self.stdout.write(self.style.NOTICE(f'[CRON] >>> {nome}'))
            try:
                call_command(cmd, *cmd_args)
                executadas += 1
            except Exception as exc:
                # Falha em um sub-command nao deve impedir os outros.
                logger.exception('[CRON] Sub-command %s falhou: %s', nome, exc)
                self.stderr.write(self.style.ERROR(f'[CRON] Falha em {nome}: {exc}'))
                falhas += 1

        prefix = '[DRY-RUN] ' if dry else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Tick {agora.strftime("%H:%M")}: '
            f'{executadas} sub-command(s) executado(s), {falhas} falha(s).'
        ))
