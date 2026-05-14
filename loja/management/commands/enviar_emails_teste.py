from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from django.core.management.base import BaseCommand

from loja.views import (
    enviar_email_abandono_1,
    enviar_email_abandono_2,
    enviar_email_abandono_3,
    enviar_email_confirmacao,
    enviar_email_pagamento_pendente,
    enviar_email_poscompra_1,
    enviar_email_poscompra_2,
    enviar_email_poscompra_3,
    enviar_email_poscompra_4,
    enviar_email_poscompra_5,
    enviar_email_rastreio,
)


class FakeRelatedList(list):
    def all(self):
        return self

    def select_related(self, *args):
        return self


class FakePedido(SimpleNamespace):
    def save(self, update_fields=None):
        return None

    def rastreio_url(self):
        return 'https://rastreamento.correios.com.br/app/index.php?objeto=BR123456789BR'

    def rastreio_transportadora(self):
        return 'Correios'


class FakeCarrinho(SimpleNamespace):
    def save(self, update_fields=None):
        return None

    def link_checkout(self):
        return 'https://www.barrsstore.com.br/checkout/'

    def total(self):
        return sum(item.subtotal() for item in self.itens)


class Command(BaseCommand):
    help = 'Envia todos os modelos automaticos de e-mail para um destinatario de teste.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            default='matheus_bibico@hotmail.com',
            help='E-mail que deve receber os testes.',
        )

    def handle(self, *args, **options):
        destino = options['email'].strip()
        pedido = self._pedido(destino)
        carrinho = self._carrinho(destino)
        envios = [
            ('pedido confirmado', lambda: enviar_email_confirmacao(pedido)),
            ('pagamento pendente', lambda: enviar_email_pagamento_pendente(pedido)),
            ('rastreio', lambda: enviar_email_rastreio(pedido)),
            ('pos-compra 1', lambda: enviar_email_poscompra_1(pedido)),
            ('pos-compra 2', lambda: enviar_email_poscompra_2(pedido)),
            ('pos-compra 3', lambda: enviar_email_poscompra_3(pedido)),
            ('pos-compra 4', lambda: enviar_email_poscompra_4(pedido)),
            ('pos-compra 5', lambda: enviar_email_poscompra_5(pedido)),
            ('carrinho abandonado 1', lambda: enviar_email_abandono_1(carrinho)),
            ('carrinho abandonado 2', lambda: enviar_email_abandono_2(carrinho)),
            ('carrinho abandonado 3', lambda: enviar_email_abandono_3(carrinho)),
        ]

        enviados = 0
        for nome, funcao in envios:
            ok = funcao()
            status = 'OK' if ok else 'FALHOU'
            self.stdout.write(f'{nome}: {status}')
            if ok:
                enviados += 1

        if enviados == len(envios):
            self.stdout.write(self.style.SUCCESS(f'Todos os {enviados} e-mails de teste foram enviados para {destino}.'))
        else:
            self.stderr.write(self.style.ERROR(f'Enviados {enviados}/{len(envios)} e-mails. Verifique BREVO_API_KEY e logs acima.'))

    def _pedido(self, destino):
        itens = FakeRelatedList([
            SimpleNamespace(nome_produto='Colar Eterno Amor', quantidade=1, preco_unitario=Decimal('89.90')),
            SimpleNamespace(nome_produto='Brinco Coracao Detalhado', quantidade=1, preco_unitario=Decimal('59.90')),
        ])
        return FakePedido(
            id=20260514,
            nome='Matheus Teste',
            email=destino,
            telefone='(11) 91322-5256',
            cpf='000.000.000-00',
            cep='08275-700',
            rua='Rua Equestre',
            numero='170',
            complemento='Casa',
            bairro='Fazenda Aricanduva',
            cidade='Sao Paulo',
            estado='SP',
            subtotal=Decimal('149.80'),
            desconto=Decimal('10.00'),
            cupom_codigo='TESTE10',
            frete=Decimal('0.00'),
            total=Decimal('139.80'),
            access_token=uuid4(),
            codigo_rastreio='BR123456789BR',
            melhor_envio_service_id=1,
            email_pagamento_pendente_enviado=False,
            email_rastreio_enviado=False,
            email_poscompra_1_enviado=False,
            email_poscompra_2_enviado=False,
            email_poscompra_3_enviado=False,
            email_poscompra_4_enviado=False,
            email_poscompra_5_enviado=False,
            itens=itens,
        )

    def _carrinho(self, destino):
        produto_1 = SimpleNamespace(nome='Colar Eterno Amor', preco=Decimal('89.90'), imagem=None)
        produto_2 = SimpleNamespace(nome='Brinco Coracao Detalhado', preco=Decimal('59.90'), imagem=None)
        itens = FakeRelatedList([
            SimpleNamespace(produto=produto_1, quantidade=1, tamanho='', subtotal=lambda: Decimal('89.90')),
            SimpleNamespace(produto=produto_2, quantidade=1, tamanho='', subtotal=lambda: Decimal('59.90')),
        ])
        return FakeCarrinho(
            email_cliente=destino,
            itens=itens,
            email_abandono_1_enviado=False,
            email_abandono_2_enviado=False,
            email_abandono_3_enviado=False,
        )
