from django.contrib import admin
from .models import Produto, Carrinho, ItemCarrinho, Pedido


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'preco', 'estoque', 'destaque', 'disponivel')
    list_editable = ('preco', 'estoque', 'destaque')
    search_fields = ('nome', 'descricao')
    list_filter = ('destaque',)

    def disponivel(self, obj):
        return obj.disponivel()
    disponivel.boolean = True
    disponivel.short_description = 'Disponível'


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'email', 'cidade', 'forma_pagamento', 'status', 'total', 'criado_em')
    list_editable = ('status',)
    list_filter = ('forma_pagamento', 'status', 'estado')
    search_fields = ('nome', 'email', 'cidade')
    readonly_fields = ('criado_em',)


@admin.register(ItemCarrinho)
class ItemCarrinhoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'quantidade', 'carrinho')


@admin.register(Carrinho)
class CarrinhoAdmin(admin.ModelAdmin):
    list_display = ('id', 'criado_em', 'quantidade_total', 'total')

    def quantidade_total(self, obj):
        return obj.quantidade_total()
    quantidade_total.short_description = 'Itens'

    def total(self, obj):
        return f'R$ {obj.total()}'
    total.short_description = 'Total'
