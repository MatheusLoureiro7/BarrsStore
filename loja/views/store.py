import json
import logging

from django.core.cache import cache
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Categoria, Pedido, Produto
from .utils import (
    get_carrinho_info,
    json_ld_dumps,
    noindex_context,
    ratelimit,
    seo_context,
    site_url,
)

logger = logging.getLogger(__name__)


def _registrar_clique_produto(produto_id):
    """Incrementa o contador de cliques no cache (flush via management command).

    Evita 1 UPDATE no DB por visita ao detalhe. O cron `flush_cliques_produtos`
    consolida os buffers no banco periodicamente.
    """
    key = f'cliques:{produto_id}'
    try:
        cache.incr(key)
    except ValueError:
        # Chave nao existia: cria com TTL de 24h (longe o suficiente para o cron pegar).
        cache.set(key, 1, 60 * 60 * 24)
    pendentes = cache.get('cliques:pendentes') or set()
    if produto_id not in pendentes:
        pendentes = set(pendentes)
        pendentes.add(produto_id)
        cache.set('cliques:pendentes', pendentes, 60 * 60 * 24)


def home(request):
    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')
    categoria_slug = request.GET.get('categoria', '')
    categoria_aliases = {
        'aneis': ['anel', 'aneis'],
        'anel': ['anel', 'aneis'],
        'brincos': ['brinco', 'brincos'],
        'brinco': ['brinco', 'brincos'],
        'colares': ['colar', 'colares'],
        'colar': ['colar', 'colares'],
        'pulseiras': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
        'pulseira': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
        'braceletes-e-pulseiras': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
        'chokers': ['choker', 'chokers'],
        'choker': ['choker', 'chokers'],
        'conjuntos': ['conjunto', 'conjuntos'],
        'conjunto': ['conjunto', 'conjuntos'],
    }

    produtos = Produto.objects.filter(visivel=True).distinct()

    if busca:
        produtos = produtos.filter(
            Q(nome__icontains=busca) | Q(descricao__icontains=busca)
        )

    if categoria_slug == 'mais-vendidos':
        produtos = produtos.filter(destaque=True)
    elif categoria_slug:
        produtos = produtos.filter(categoria__slug__in=categoria_aliases.get(categoria_slug, [categoria_slug]))

    if ordem == 'menor':
        produtos = produtos.order_by('-destaque', 'preco', '-criado_em', '-id')
    elif ordem == 'maior':
        produtos = produtos.order_by('-destaque', '-preco', '-criado_em', '-id')
    elif ordem == 'nome':
        produtos = produtos.order_by('-destaque', 'nome', '-criado_em', '-id')
    else:
        produtos = produtos.order_by('-destaque', '-criado_em', '-id')

    # Cache do count() (query potencialmente cara em catalogo grande). TTL 60s.
    # Vary por filtros que mudam o resultado.
    total_cache_key = f'home:count:v=1:q={busca}:o={ordem}:c={categoria_slug}'
    total_produtos = cache.get(total_cache_key)
    if total_produtos is None:
        total_produtos = produtos.count()
        cache.set(total_cache_key, total_produtos, 60)
    try:
        page_number = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page_number = 1
    per_page = 12
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_params.pop('partial', None)
    base_query = query_params.urlencode()

    # Resposta parcial usada pelo infinite scroll do front: devolve so o chunk daquela pagina.
    is_partial = (
        request.GET.get('partial') == '1'
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    )
    if is_partial:
        from django.template.loader import render_to_string
        inicio = (page_number - 1) * per_page
        fim = page_number * per_page
        chunk = list(produtos[inicio:fim])
        html = render_to_string('partials/product_cards_chunk.html', {'produtos': chunk}, request=request)
        return JsonResponse({
            'html': html,
            'has_next': total_produtos > fim,
            'next_page': page_number + 1 if total_produtos > fim else 0,
        })

    produtos_pagina = produtos[:page_number * per_page]
    has_next_page = total_produtos > page_number * per_page
    next_page_url = ''
    if has_next_page:
        next_query = query_params.copy()
        next_query['page'] = page_number + 1
        next_page_url = f'?{next_query.urlencode()}#produtos'

    # Lista de categorias raramente muda; cache 5min reduz query desnecessaria.
    categorias = cache.get('home:categorias:v=1')
    if categorias is None:
        categorias = list(Categoria.objects.all())
        cache.set('home:categorias:v=1', categorias, 300)
    # So noindex em buscas internas (q=); categoria e ordem continuam indexaveis.
    seo = seo_context(
        request,
        'Barrs Store - Acessorios modernos e exclusivos',
        'Compre acessorios femininos modernos na Barrs Store: aneis, brincos, colares e pulseiras com envio para todo o Brasil.',
        robots='noindex, follow' if request.GET.get('q') else 'index, follow',
    )

    context = {
        'produtos': produtos_pagina,
        'has_next_page': has_next_page,
        'next_page_url': next_page_url,
        'next_page_number': page_number + 1 if has_next_page else 0,
        'base_query': base_query,
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': total_produtos,
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
    }
    context.update(seo)
    return render(request, 'home.html', context)


# ── DETALHE DO PRODUTO ─────────────────────────────────────────────
def detalhe_produto(request, slug):
    produto = get_object_or_404(Produto, slug=slug, visivel=True)
    if not request.user.is_staff:
        _registrar_clique_produto(produto.pk)
    # Relacionados raramente mudam; cache 5min por produto reduz queries no detalhe.
    rel_cache_key = f'detalhe:relacionados:v=1:cat={produto.categoria_id or 0}:exc={produto.id}'
    relacionados = cache.get(rel_cache_key)
    if relacionados is None:
        relacionados = list(
            Produto.objects.filter(visivel=True, estoque__gt=0, categoria=produto.categoria)
            .exclude(id=produto.id)[:4]
        )
        if not relacionados:
            relacionados = list(
                Produto.objects.filter(visivel=True, estoque__gt=0).exclude(id=produto.id)[:4]
            )
        cache.set(rel_cache_key, relacionados, 300)
    image_url = site_url(produto.imagem.url) if produto.imagem else ''
    seo = seo_context(
        request,
        produto.get_seo_title(),
        produto.get_meta_description(),
        image_url=image_url,
    )
    breadcrumb_schema = {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': [
            {
                '@type': 'ListItem',
                'position': 1,
                'name': 'Inicio',
                'item': site_url('/'),
            },
            {
                '@type': 'ListItem',
                'position': 2,
                'name': 'Produtos',
                'item': site_url('/#produtos'),
            },
            {
                '@type': 'ListItem',
                'position': 3,
                'name': produto.nome,
                'item': seo['seo_canonical'],
            },
        ],
    }
    context = {
        'produto': produto,
        'relacionados': relacionados,
        'qtd_carrinho': get_carrinho_info(request),
        'preco_schema': str(produto.preco).replace(',', '.'),
        'product_schema_json_ld': produto.get_schema_json_ld(
            absolute_url=seo['seo_canonical'],
            absolute_image_url=image_url,
        ),
        'breadcrumb_schema_json_ld': json_ld_dumps(breadcrumb_schema),
    }
    context.update(seo)
    return render(request, 'detalhe.html', context)


def detalhe_produto_id(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id, visivel=True)
    return redirect(produto.get_absolute_url(), permanent=True)


def robots_txt(request):
    linhas = [
        'User-agent: *',
        'Disallow: /painel/',
        'Disallow: /admin/',
        'Disallow: /carrinho/',
        'Disallow: /finalizar/',
        'Disallow: /pagamento/',
        'Disallow: /minha-conta/',
        'Disallow: /login/',
        'Disallow: /cadastro/',
        'Allow: /',
        f'Sitemap: {site_url("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(linhas), content_type='text/plain')


def google_site_verification(request):
    return HttpResponse(
        'google-site-verification: google86e9062d166d5e41.html',
        content_type='text/html',
    )


def pagina_404(request, exception):
    return render(request, '404.html', status=404)


def entrega(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Entrega e trocas - Barrs Store', 'Veja prazos de envio e informacoes de trocas e devolucoes da Barrs Store para comprar com tranquilidade.'),
    }
    return render(request, 'entrega.html', context)


def medidas(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Guia de medidas - Barrs Store', 'Consulte o guia de medidas da Barrs Store para escolher aneis e acessorios com mais seguranca.'),
    }
    return render(request, 'medidas.html', context)


def garantia(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(
            request,
            'Garantia Barrs Store - Semijoias com 12 meses de garantia',
            'Entenda a garantia de 12 meses da Barrs Store, o que cobre, o que nao cobre e como cuidar das suas semijoias.',
        ),
    }
    return render(request, 'garantia.html', context)


@ratelimit(key='ip', rate='10/m', method='GET', block=True)
def rastrear_pedido(request):
    pedido = None
    erro = ''
    if request.GET.get('pedido') or request.GET.get('email'):
        pedido_id = request.GET.get('pedido', '').strip().replace('#', '')
        email = request.GET.get('email', '').strip()
        if not pedido_id or not email:
            erro = 'Informe o numero do pedido e o e-mail da compra.'
        else:
            try:
                pedido = Pedido.objects.get(id=pedido_id, email__iexact=email)
            except (Pedido.DoesNotExist, ValueError):
                erro = 'Nao encontramos um pedido com esses dados.'

    context = {
        'pedido': pedido,
        'erro': erro,
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Rastrear pedido - Barrs Store', 'Acompanhe o status e o codigo de rastreio do seu pedido na Barrs Store.'),
    }
    return render(request, 'rastrear_pedido.html', context)


def sobre(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Sobre a Barrs Store', 'Conheca a Barrs Store, uma loja de acessorios modernos com atendimento humanizado e rapido.'),
    }
    return render(request, 'sobre.html', context)


def contato(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Contato - Barrs Store', 'Fale com a Barrs Store pelo WhatsApp para tirar duvidas sobre produtos, pedidos e entregas.'),
    }
    return render(request, 'contato.html', context)


def politica(request):
    context = {
        'qtd_carrinho': get_carrinho_info(request),
        **seo_context(request, 'Politica de privacidade - Barrs Store', 'Leia a politica de privacidade da Barrs Store e entenda como seus dados sao protegidos.'),
    }
    return render(request, 'politica.html', context)
