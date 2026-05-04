import os

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Envia um e-mail simples pelo Brevo para testar as variaveis do Railway.'

    def add_arguments(self, parser):
        parser.add_argument('email', help='E-mail que deve receber o teste.')

    def handle(self, *args, **options):
        destino = options['email'].strip()
        api_key = os.environ.get('BREVO_API_KEY', '').strip()
        from_email = os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip()

        if not api_key:
            self.stderr.write(self.style.ERROR('BREVO_API_KEY nao configurada no ambiente.'))
            return

        resposta = requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'accept': 'application/json',
                'api-key': api_key,
                'Content-Type': 'application/json',
            },
            json={
                'sender': {'name': 'Barrs Store', 'email': from_email},
                'to': [{'email': destino, 'name': 'Teste Barrs Store'}],
                'subject': 'Teste de e-mail - Barrs Store',
                'htmlContent': '<p>Se voce recebeu este e-mail, o Brevo esta configurado corretamente.</p>',
            },
            timeout=15,
        )

        self.stdout.write(f'BREVO_FROM_EMAIL={from_email}')
        self.stdout.write(f'Status Brevo: {resposta.status_code}')
        self.stdout.write(f'Resposta Brevo: {resposta.text[:800]}')

        if resposta.status_code < 400:
            self.stdout.write(self.style.SUCCESS('E-mail de teste enviado.'))
        else:
            self.stderr.write(self.style.ERROR('Brevo recusou o envio. Veja a resposta acima.'))
