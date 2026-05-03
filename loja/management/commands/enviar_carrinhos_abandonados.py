import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import Carrinho
from loja.whatsapp import enviar_whatsapp, formatar_numero_brasil


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Envia WhatsApp para carrinhos abandonados parados ha 45 minutos.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutos',
            type=int,
            default=45,
            help='Tempo minimo de carrinho parado antes do envio. Padrao: 45.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostra o que seria enviado sem chamar a API.',
        )
        parser.add_argument(
            '--reenviar',
            action='store_true',
            help='Inclui carrinhos que ja foram marcados como enviados. Use apenas para teste.',
        )

    def handle(self, *args, **options):
        minutos = max(options['minutos'], 0)
        limite = timezone.now() - timedelta(minutes=minutos)

        filtros = {
            'telefone_cliente__gt': '',
            'aceita_whatsapp': True,
            'atualizado_em__lte': limite,
            'itens__isnull': False,
        }
        if not options['reenviar']:
            filtros['whatsapp_abandono_enviado'] = False

        carrinhos = (
            Carrinho.objects
            .filter(**filtros)
            .prefetch_related('itens__produto')
            .distinct()
        )

        total = carrinhos.count()
        self.stdout.write(f'[CARRINHO] {total} carrinho(s) elegivel(is) para WhatsApp.')

        for carrinho in carrinhos:
            link_checkout = carrinho.link_checkout()
            mensagem = (
                'Oii 👋 vimos que você deixou algumas peças no carrinho da Barrs Store 💎\n\n'
                'Seu carrinho ainda está salvo.\n'
                'Quer ajuda para finalizar?\n\n'
                f'Acesse aqui: {link_checkout}'
            )

            if options['dry_run']:
                numero_formatado = formatar_numero_brasil(carrinho.telefone_cliente)
                self.stdout.write(
                    f'[DRY-RUN] Carrinho {carrinho.id}: enviaria para {carrinho.telefone_cliente} -> {numero_formatado}'
                )
                continue

            resultado = enviar_whatsapp(carrinho.telefone_cliente, mensagem)
            self.stdout.write(
                f"[WHATSAPP] Carrinho {carrinho.id}: numero={resultado['numero']} "
                f"status={resultado['status_code']} resposta={resultado['body']}"
            )

            if resultado['ok']:
                carrinho.whatsapp_abandono_enviado = True
                carrinho.whatsapp_abandono_enviado_em = timezone.now()
                carrinho.save(update_fields=[
                    'whatsapp_abandono_enviado',
                    'whatsapp_abandono_enviado_em',
                    'atualizado_em',
                ])
                logger.info('[CARRINHO] WhatsApp de abandono enviado. Carrinho=%s', carrinho.id)
                self.stdout.write(self.style.SUCCESS(
                    f'[CARRINHO] Enviado para carrinho {carrinho.id}.'
                ))
            else:
                logger.error('[CARRINHO] Falha ao enviar WhatsApp. Carrinho=%s', carrinho.id)
                self.stdout.write(self.style.ERROR(
                    f'[CARRINHO] Falhou no carrinho {carrinho.id}.'
                ))
