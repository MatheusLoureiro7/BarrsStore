from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from .models import Produto, Carrinho, ItemCarrinho, Pedido, Categoria, TamanhoAnel
import requests as http_requests
import os


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('icone', 'nome', 'slug')
    prepopulated_fields = {'slug': ('nome',)}


class TamanhoInline(admin.TabularInline):
    model = TamanhoAnel
    extra = 4
    fields = ('numero', 'estoque')


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'categoria', 'tipo', 'preco', 'estoque', 'destaque')
    list_editable = ('preco', 'estoque', 'destaque')
    list_filter = ('destaque', 'categoria', 'tipo')
    search_fields = ('nome', 'descricao', 'slug')
    prepopulated_fields = {'slug': ('nome',)}
    fieldsets = (
        ('Produto', {
            'fields': ('nome', 'slug', 'descricao', 'preco', 'imagem', 'estoque', 'destaque', 'categoria', 'tipo')
        }),
        ('SEO', {
            'fields': ('meta_description', 'imagem_alt')
        }),
        ('Controle interno', {
            'fields': ('codigo_interno', 'estoque_proprio')
        }),
    )
    inlines = [TamanhoInline]


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'email', 'cidade', 'status', 'total', 'criado_em')
    list_editable = ('status',)
    list_filter = ('status', 'forma_pagamento', 'estado')
    search_fields = ('nome', 'email', 'cidade')
    readonly_fields = ('criado_em', 'access_token')


@admin.register(ItemCarrinho)
class ItemCarrinhoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'quantidade', 'carrinho')


@admin.register(Carrinho)
class CarrinhoAdmin(admin.ModelAdmin):
    list_display = ('id', 'criado_em')
