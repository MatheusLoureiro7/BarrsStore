from django.contrib import admin
from .models import Produto, Carrinho, ItemCarrinho, Pedido, Categoria, TamanhoAnel


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('icone', 'nome', 'slug')
    prepopulated_fields = {'slug': ('nome',)}


class TamanhoInline(admin.TabularInline):
    model = TamanhoAnel
    extra = 6
    fields = ('numero', 'estoque')


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'tipo', 'preco', 'estoque', 'destaque', 'disponivel')
    list_editable = ('preco', 'estoque', 'destaque')
    list_filter = ('destaque', 'categoria', 'tipo')
    search_fields = ('nome', 'descricao')
    inlines = [TamanhoInline]

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
    list_display = ('produto', 'quantidade', 'tamanho', 'carrinho')


@admin.register(Carrinho)
class CarrinhoAdmin(admin.ModelAdmin):
    list_display = ('id', 'criado_em', 'quantidade_total', 'total')

    def quantidade_total(self, obj):
        return obj.quantidade_total()
    quantidade_total.short_description = 'Itens'

    def total(self, obj):
        return f'R$ {obj.total()}'
    total.short_description = 'Total'
