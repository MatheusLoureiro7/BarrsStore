from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Produto, Categoria


class ProdutoSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return Produto.objects.filter(visivel=True).order_by('-criado_em')

    def lastmod(self, obj):
        return obj.criado_em


class CategoriaSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Categoria.objects.all()

    def location(self, obj):
        return reverse('categoria_detalhe', kwargs={'categoria_slug': obj.slug})


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return ['home', 'sobre', 'contato', 'entrega', 'garantia', 'politica', 'medidas', 'rastrear_pedido']

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == 'home' else 0.6
