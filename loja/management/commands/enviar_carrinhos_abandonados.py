import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from loja.models import Carrinho
from loja.whatsapp import enviar_whatsapp, formatar_numero_brasil
from loja.views import enviar_email_abandono_1, enviar_email_abandono_2, enviar_email_abandono_3

logger = logging.getLogger(__name__)

# (flag, função, janela_min_min, janela_max_min)
EMAIL_SEQUENCIA = [
    ('email_abandono_1_enviado', enviar_email_abandono_1, 45, 360),
    ('email_abandono_2_enviado', enviar_email_abandono_2, 22 * 60, 26 * 60),
    ('email_abandono_3_enviado', enviar_email_abandono_3, 44 * 60, 52 * 60),
]


class Command(BaseCommand):
    help = 'Envia WhatsApp e sequência premium de e-mails para carrinhos abandonados.'

    def add_arguments(self, parser):
        parser.add_argument('--minutos', type=int, default=45,
                            help='Tempo mínimo de carrinho parado para WhatsApp. Padrão: 45.')
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostra o que seria enviado sem chamar a API.')
        parser.add_argument('--reenviar', action='store_true',
                            help='Inclui carrinhos já marcados como enviados. Só para teste.')

    def handle(self, *args, **options):
        minutos = max(options['minutos'], 0)
        dry_run = options['dry_run']
        agora = timezone.now()

        # ── WhatsApp (comportamento original) ─────────────────────────────
        limite_wa = agora - timedelta(minutes=minutos)
        filtros_wa = {
            'telefone_cliente__gt': '',
            'aceita_whatsapp': True,
            'atualizado_em__lte': limite_wa,
            'itens__isnull': False,
        }
        if not options['reenviar']:
            filtros_wa['whatsapp_abandono_enviado'] = False

        carrinhos_wa = (
            Carrinho.objects
            .filter(**filtros_wa)
            .prefetch_related('itens__produto')
            .distinct()
        )

        total_wa = carrinhos_wa.count()
        self.stdout.write(f'[WHATSAPP] {total_wa} carrinho(s) elegível(is) para WhatsApp.')

        for carrinho in carrinhos_wa:
            link_checkout = carrinho.link_checkout()
            mensagem = (
                'Oii 👋 vimos que você deixou algumas peças no carrinho da Barrs Store 💎\n\n'
                'Seu carrinho ainda está salvo.\n'
                'Quer ajuda para finalizar?\n\n'
                f'Acesse aqui: {link_checkout}'
            )

            if dry_run:
                numero_formatado = formatar_numero_brasil(carrinho.telefone_cliente)
                self.stdout.write(f'  [DRY-RUN] Carrinho {carrinho.id}: WA → {numero_formatado}')
                continue

            resultado = enviar_whatsapp(carrinho.telefone_cliente, mensagem)
            if resultado['ok']:
                carrinho.whatsapp_abandono_enviado = True
                carrinho.whatsapp_abandono_enviado_em = agora
                carrinho.save(update_fields=['whatsapp_abandono_enviado', 'whatsapp_abandono_enviado_em', 'atualizado_em'])
                logger.info('[CARRINHO] WhatsApp enviado. Carrinho=%s', carrinho.id)
                self.stdout.write(self.style.SUCCESS(f'  [WA] Carrinho {carrinho.id} enviado.'))
            else:
                logger.error('[CARRINHO] Falha WhatsApp. Carrinho=%s', carrinho.id)
                self.stdout.write(self.style.ERROR(f'  [WA] Carrinho {carrinho.id} falhou.'))

        # ── Sequência de e-mail premium ────────────────────────────────────
        total_email = 0
        for flag, funcao, min_janela, max_janela in EMAIL_SEQUENCIA:
            janela_inicio = agora - timedelta(minutes=max_janela)
            janela_fim = agora - timedelta(minutes=min_janela)

            carrinhos_email = (
                Carrinho.objects
                .filter(
                    email_cliente__gt='',
                    atualizado_em__gte=janela_inicio,
                    atualizado_em__lte=janela_fim,
                    itens__isnull=False,
                    **{flag: False},
                )
                .prefetch_related('itens__produto')
                .distinct()
            )

            count = carrinhos_email.count()
            if not count:
                continue

            self.stdout.write(f'[EMAIL] {flag}: {count} carrinho(s) elegível(is)')

            for carrinho in carrinhos_email:
                if dry_run:
                    self.stdout.write(f'  [DRY-RUN] Carrinho {carrinho.id} → {carrinho.email_cliente}')
                    continue

                ok = funcao(carrinho)
                if ok:
                    total_email += 1
                    self.stdout.write(self.style.SUCCESS(f'  [EMAIL] Carrinho {carrinho.id} enviado.'))
                else:
                    self.stdout.write(self.style.ERROR(f'  [EMAIL] Carrinho {carrinho.id} falhou.'))

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f'[CARRINHOS] E-mails enviados: {total_email}'))
