from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Produto


class ProdutoSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return Produto.objects.filter(estoque__gt=0).order_by('-criado_em')

    def lastmod(self, obj):
        return obj.criado_em


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return ['home', 'sobre', 'contato', 'entrega', 'politica', 'medidas', 'rastrear_pedido']

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == 'home' else 0.6
