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
]