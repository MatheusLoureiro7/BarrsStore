from django.contrib import admin
from django.utils.html import format_html
from django.contrib import messages
from .models import Produto, Carrinho, ItemCarrinho, Pedido, Categoria, TamanhoAnel, Cupom
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
    list_display = ('id', 'nome', 'email', 'cidade', 'status', 'total', 'codigo_rastreio', 'criado_em')
    list_editable = ('status',)
    list_filter = ('status', 'forma_pagamento', 'estado')
    search_fields = ('nome', 'email', 'cidade', 'codigo_rastreio')
    readonly_fields = ('criado_em', 'access_token')

    def save_model(self, request, obj, form, change):
        status_anterior = None
        codigo_anterior = ''
        if change and obj.pk:
            antigo = Pedido.objects.filter(pk=obj.pk).first()
            if antigo:
                status_anterior = antigo.status
                codigo_anterior = antigo.codigo_rastreio
        super().save_model(request, obj, form, change)
        if obj.codigo_rastreio and not obj.email_rastreio_enviado:
            from .views import enviar_email_rastreio
            if enviar_email_rastreio(obj):
                obj.email_rastreio_enviado = True
                if obj.status == 'confirmado':
                    obj.status = 'enviado'
                obj.save(update_fields=['email_rastreio_enviado', 'status'])
                self.message_user(request, 'E-mail de rastreio enviado ao cliente.', messages.SUCCESS)
        elif change and status_anterior != obj.status and obj.status == 'enviado' and obj.codigo_rastreio and codigo_anterior == obj.codigo_rastreio:
            from .views import enviar_email_rastreio
            if enviar_email_rastreio(obj):
                obj.email_rastreio_enviado = True
                obj.save(update_fields=['email_rastreio_enviado'])


@admin.register(Cupom)
class CupomAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'tipo', 'valor', 'ativo', 'uso_maximo', 'usado', 'valor_minimo')
    list_editable = ('ativo',)
    list_filter = ('ativo', 'tipo')
    search_fields = ('codigo',)


@admin.register(ItemCarrinho)
class ItemCarrinhoAdmin(admin.ModelAdmin):
    list_display = ('produto', 'quantidade', 'carrinho')


@admin.register(Carrinho)
class CarrinhoAdmin(admin.ModelAdmin):
    list_display = ('id', 'criado_em')
