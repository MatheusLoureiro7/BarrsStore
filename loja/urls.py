from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('produto/<int:produto_id>/', views.detalhe_produto, name='detalhe_produto'),
    path('add/<int:produto_id>/', views.adicionar_carrinho, name='add_carrinho'),
    path('carrinho/', views.ver_carrinho, name='carrinho'),
    path('remover/<int:item_id>/', views.remover_item, name='remover_item'),
    path('deletar/<int:item_id>/', views.deletar_item, name='deletar_item'),
    path('finalizar/', views.checkout, name='finalizar_compra'),
    path('pedido/<int:pedido_id>/', views.confirmacao, name='confirmacao'),
    path('sobre/', views.sobre, name='sobre'),
    path('contato/', views.contato, name='contato'),
    path('politica/', views.politica, name='politica'),

    # Mercado Pago
    path('pagamento/preferencia/<int:pedido_id>/', views.criar_preferencia, name='criar_preferencia'),
    path('pagamento/sucesso/<int:pedido_id>/', views.pagamento_sucesso, name='pagamento_sucesso'),
    path('pagamento/falha/<int:pedido_id>/', views.pagamento_falha, name='pagamento_falha'),
    path('pagamento/pendente/<int:pedido_id>/', views.pagamento_pendente, name='pagamento_pendente'),
    path('pagamento/webhook/', views.webhook_mercadopago, name='webhook_mp'),

    # Autenticação e área do cliente
    path('cadastro/', views.cadastro, name='cadastro'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('minha-conta/', views.minha_conta, name='minha_conta'),
    path('minha-conta/pedido/<int:pedido_id>/', views.detalhe_pedido, name='detalhe_pedido'),
]
