import logging
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone as django_timezone

from ..models import Carrinho, EmailPendente, Pedido, Produto

logger = logging.getLogger(__name__)


# ── DASHBOARD ADMIN DE SAÚDE OPERACIONAL ─────────────────────────
@staff_member_required(login_url='/painel/login/')
def dashboard_saude(request):
    """Painel rapido com pedidos pendentes, falhas de envio, fila de emails
    e receita do periodo. Visivel apenas para staff."""
    agora = django_timezone.now()
    hoje = agora.date()
    inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_semana = inicio_dia - timedelta(days=hoje.weekday())
    inicio_mes = inicio_dia.replace(day=1)

    # Pedidos de atencao. list(...) materializa para usar len() abaixo sem queries extras.
    pedidos_pendentes = list(
        Pedido.objects.filter(
            status='pendente', criado_em__lte=agora - timedelta(hours=1),
        ).order_by('-criado_em')[:20]
    )
    pedidos_sem_etiqueta = list(
        Pedido.objects.filter(status='confirmado')
        .filter(Q(melhor_envio_status='erro') | Q(melhor_envio_order_id=''))
        .order_by('-criado_em')[:20]
    )

    # Fila de emails
    emails_erro = list(EmailPendente.objects.filter(status='erro').order_by('-atualizado_em')[:20])
    emails_pendentes_count = EmailPendente.objects.filter(status='pendente').count()
    emails_erro_count = EmailPendente.objects.filter(status='erro').count()

    # Carrinhos abandonados (com email, ultimos 7d)
    carrinhos_abandonados = list(
        Carrinho.objects.filter(
            email_cliente__isnull=False,
            atualizado_em__lte=agora - timedelta(hours=1),
            atualizado_em__gte=agora - timedelta(days=7),
        ).exclude(email_cliente='').order_by('-atualizado_em')[:15]
    )

    # Receita confirmada
    def receita(desde):
        return Pedido.objects.filter(
            status__in=['confirmado', 'enviado', 'entregue'],
            criado_em__gte=desde,
        ).aggregate(total=Sum('total'), n=Count('id'))

    top_produtos = Produto.objects.filter(visivel=True, cliques__gt=0).order_by('-cliques')[:5]

    context = {
        'pedidos_pendentes': pedidos_pendentes,
        'pedidos_pendentes_count': len(pedidos_pendentes),
        'pedidos_sem_etiqueta': pedidos_sem_etiqueta,
        'pedidos_sem_etiqueta_count': len(pedidos_sem_etiqueta),
        'emails_erro': emails_erro,
        'emails_pendentes_count': emails_pendentes_count,
        'emails_erro_count': emails_erro_count,
        'carrinhos_abandonados': carrinhos_abandonados,
        'carrinhos_count': len(carrinhos_abandonados),
        'receita_dia': receita(inicio_dia),
        'receita_semana': receita(inicio_semana),
        'receita_mes': receita(inicio_mes),
        'top_produtos': top_produtos,
        'agora': agora,
    }
    return render(request, 'admin/dashboard_saude.html', context)
