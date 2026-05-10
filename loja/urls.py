from django.urls import path
from django.contrib.sitemaps.views import sitemap
from . import views
from .sitemaps import ProdutoSitemap, StaticViewSitemap
from django.views.generic.base import RedirectView

sitemaps = {
    'produtos': ProdutoSitemap,
    'paginas': StaticViewSitemap,
}

urlpatterns = [
    path('', views.home, name='home'),
    path('robots.txt', views.robots_txt, name='robots_txt'),
    path('google86e9062d166d5e41.html', views.google_site_verification, name='google_site_verification'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    path('produto/<int:produto_id>/', views.detalhe_produto_id, name='detalhe_produto_id'),
    path('produto/<slug:slug>/', views.detalhe_produto, name='detalhe_produto'),
    path('add/<int:produto_id>/', views.adicionar_carrinho, name='add_carrinho'),
    path('carrinho/', views.ver_carrinho, name='carrinho'),
    path('remover/<int:item_id>/', views.remover_item, name='remover_item'),
    path('deletar/<int:item_id>/', views.deletar_item, name='deletar_item'),
    path('carrinho/salvar-contato/', views.salvar_contato_carrinho, name='salvar_contato_carrinho'),
    path('carrinho/aplicar-cupom/', views.aplicar_cupom_ajax, name='aplicar_cupom_ajax'),
    path('finalizar/', views.checkout, name='finalizar_compra'),
    path('pedido/<int:pedido_id>/<uuid:token>/', views.confirmacao, name='confirmacao'),
    path('sobre/', views.sobre, name='sobre'),
    path('contato/', views.contato, name='contato'),
    path('politica/', views.politica, name='politica'),
    path('entrega/', views.entrega, name='entrega'),
    path('medidas/', views.medidas, name='medidas'),
    path('garantia/', views.garantia, name='garantia'),
    path('rastrear/', views.rastrear_pedido, name='rastrear_pedido'),
    path('frete/calcular/', views.calcular_frete_ajax, name='calcular_frete'),
    path('frete/melhor-envio/', views.calcular_frete_melhor_envio, name='calcular_frete_me'),

    # Mercado Pago
    path('pagamento/preferencia/<int:pedido_id>/<uuid:token>/', views.criar_preferencia, name='criar_preferencia'),
    path('pagamento/sucesso/<int:pedido_id>/<uuid:token>/', views.pagamento_sucesso, name='pagamento_sucesso'),
    path('pagamento/falha/<int:pedido_id>/<uuid:token>/', views.pagamento_falha, name='pagamento_falha'),
    path('pagamento/pendente/<int:pedido_id>/<uuid:token>/', views.pagamento_pendente, name='pagamento_pendente'),
    path('pagamento/status/<int:pedido_id>/<uuid:token>/', views.status_pagamento, name='status_pagamento'),
    path('pagamento/webhook/', views.webhook_mercadopago, name='webhook_mp'),

    # Autenticação e área do cliente
    path('cadastro/', views.cadastro, name='cadastro'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('minha-conta/', views.minha_conta, name='minha_conta'),
    path('minha-conta/pedido/<int:pedido_id>/', views.detalhe_pedido, name='detalhe_pedido'),
]
