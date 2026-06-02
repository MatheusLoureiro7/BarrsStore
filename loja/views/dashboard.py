import calendar as cal_lib
import logging
from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone as django_timezone

from ..models import Carrinho, EmailPendente, Pedido, Produto

logger = logging.getLogger(__name__)

_MESES_PT = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


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

    # Filtro de mês selecionado via ?mes=YYYY-MM
    mes_param = request.GET.get('mes', '') or hoje.strftime('%Y-%m')
    try:
        ano_sel, mes_sel = map(int, mes_param.split('-'))
        # Range razoavel: do ano fundacional da loja ate o proximo ano.
        if not (2020 <= ano_sel <= hoje.year + 1) or not (1 <= mes_sel <= 12):
            raise ValueError('mes fora do range permitido')
        inicio_mes_sel = inicio_dia.replace(year=ano_sel, month=mes_sel, day=1)
        _, n_dias = cal_lib.monthrange(ano_sel, mes_sel)
        fim_mes_sel = inicio_mes_sel.replace(day=n_dias, hour=23, minute=59, second=59, microsecond=999999)
        mes_label = f"{_MESES_PT[mes_sel - 1]}/{ano_sel}"
    except (ValueError, TypeError, OverflowError):
        mes_param = hoje.strftime('%Y-%m')
        inicio_mes_sel = inicio_mes
        _, n_dias = cal_lib.monthrange(hoje.year, hoje.month)
        fim_mes_sel = inicio_mes_sel.replace(day=n_dias, hour=23, minute=59, second=59, microsecond=999999)
        mes_label = f"{_MESES_PT[hoje.month - 1]}/{hoje.year}"

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
    def receita(desde, ate=None):
        qs = Pedido.objects.filter(
            status__in=['confirmado', 'enviado', 'entregue'],
            criado_em__gte=desde,
        )
        if ate is not None:
            qs = qs.filter(criado_em__lte=ate)
        return qs.aggregate(total=Sum('total'), n=Count('id'))

    receita_mes_sel = receita(inicio_mes_sel, fim_mes_sel)
    ticket_medio_mes = (
        receita_mes_sel['total'] / receita_mes_sel['n']
        if receita_mes_sel['n'] else None
    )

    # Faturamento total (todos os tempos) e ticket médio geral
    faturamento_total = Pedido.objects.filter(
        status__in=['confirmado', 'enviado', 'entregue']
    ).aggregate(total=Sum('total'), n=Count('id'))
    ticket_medio_geral = (
        faturamento_total['total'] / faturamento_total['n']
        if faturamento_total['n'] else None
    )

    # Meses com pedidos confirmados para o seletor
    meses_disponiveis = list(
        Pedido.objects.filter(status__in=['confirmado', 'enviado', 'entregue'])
        .dates('criado_em', 'month', order='DESC')
    )

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
        'receita_mes': receita_mes_sel,
        'ticket_medio_mes': ticket_medio_mes,
        'faturamento_total': faturamento_total,
        'ticket_medio_geral': ticket_medio_geral,
        'mes_selecionado': mes_param,
        'mes_label': mes_label,
        'meses_disponiveis': meses_disponiveis,
        'top_produtos': top_produtos,
        'agora': agora,
    }
    return render(request, 'admin/dashboard_saude.html', context)
