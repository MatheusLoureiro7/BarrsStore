import os

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import EmailPendente


class Command(BaseCommand):
    help = 'Reenvia e-mails pendentes que falharam na Brevo.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=30)
        parser.add_argument('--max-tentativas', type=int, default=5)

    def handle(self, *args, **options):
        api_key = os.environ.get('BREVO_API_KEY', '').strip()
        if not api_key:
            self.stderr.write('BREVO_API_KEY nao configurada.')
            return

        pendentes = EmailPendente.objects.filter(
            status__in=['pendente', 'erro'],
            tentativas__lt=options['max_tentativas'],
        ).order_by('criado_em')[:options['limit']]

        enviados = 0
        falhas = 0
        for email in pendentes:
            email.tentativas += 1
            try:
                resposta = requests.post(
                    'https://api.brevo.com/v3/smtp/email',
                    headers={'accept': 'application/json', 'api-key': api_key, 'Content-Type': 'application/json'},
                    json=email.payload,
                    timeout=10,
                )
                if resposta.status_code < 400:
                    email.status = 'enviado'
                    email.ultimo_erro = ''
                    email.enviado_em = timezone.now()
                    enviados += 1
                else:
                    email.status = 'erro'
                    email.ultimo_erro = f'Brevo status {resposta.status_code}'
                    falhas += 1
            except Exception as exc:
                email.status = 'erro'
                email.ultimo_erro = str(exc)[:1000]
                falhas += 1
            email.save(update_fields=['status', 'tentativas', 'ultimo_erro', 'enviado_em', 'atualizado_em'])

        self.stdout.write(self.style.SUCCESS(f'E-mails enviados: {enviados}. Falhas: {falhas}.'))
