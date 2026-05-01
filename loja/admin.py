from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
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
    list_display = ('nome', 'categoria', 'tipo', 'preco', 'estoque', 'estoque_proprio', 'destaque', 'disponivel_tag', 'codigo_interno')
    list_editable = ('preco', 'estoque', 'destaque', 'estoque_proprio')
    list_filter = ('destaque', 'categoria', 'tipo', 'estoque_proprio')
    search_fields = ('nome', 'descricao', 'codigo_interno')
    inlines = [TamanhoInline]

    fieldsets = (
        ('Informações principais', {
            'fields': ('nome', 'descricao', 'categoria', 'tipo', 'imagem', 'preco')
        }),
        ('Estoque', {
            'fields': ('estoque', 'estoque_proprio'),
            'description': '⚠️ "Estoque próprio" = produto já em mãos. Se desmarcado, será buscado sob demanda após o pedido.'
        }),
        ('Interno (não aparece no site)', {
            'fields': ('codigo_interno', 'destaque'),
            'classes': ('collapse',),
        }),
    )

    def disponivel_tag(self, obj):
        if obj.disponivel():
            return '<span style="color:green;font-weight:bold">✓ Sim</span>'
        return '<span style="color:red;font-weight:bold">✗ Não</span>'
    disponivel_tag.short_description = 'Disponível'


def enviar_email_rastreio(pedido):
    """Envia email com código de rastreio ao cliente."""
    try:
        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;background:#F5F2EC;font-family:'Arial',sans-serif">
          <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(107,94,83,0.08)">
            <div style="background:#8A947C;padding:32px 40px;text-align:center">
              <h1 style="color:#fff;font-size:24px;margin:0">Barrs Store</h1>
              <p style="color:#E8EDE3;font-size:13px;margin:8px 0 0">Acessórios modernos e exclusivos</p>
            </div>
            <div style="padding:40px">
              <div style="text-align:center;margin-bottom:28px">
                <div style="font-size:48px;margin-bottom:16px">📦</div>
                <h2 style="color:#3d2d20;font-size:22px;margin:0 0 8px">Seu pedido foi enviado!</h2>
                <p style="color:#9E9488;font-size:14px;margin:0">Olá, <strong style="color:#6B5E53">{pedido.nome}</strong>! Sua encomenda está a caminho.</p>
              </div>

              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px;text-align:center">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 8px">Pedido #{pedido.id}</p>
                <p style="font-size:13px;color:#6B5E53;margin:0 0 16px">Código de rastreio:</p>
                <div style="background:#fff;border:2px solid #8A947C;border-radius:8px;padding:14px;font-size:20px;font-weight:700;color:#8A947C;letter-spacing:3px;font-family:monospace">
                  {pedido.codigo_rastreio}
                </div>
                <p style="font-size:12px;color:#9E9488;margin:12px 0 0">Use este código para rastrear no site dos Correios</p>
              </div>

              <div style="text-align:center;margin-bottom:24px">
                <a href="https://www.correios.com.br/rastreamento/" target="_blank"
                   style="display:inline-block;padding:12px 28px;background:#8A947C;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">
                  🔍 Rastrear meu pedido
                </a>
              </div>

              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">Endereço de entrega</p>
                <p style="font-size:14px;color:#6B5E53;margin:0;line-height:1.7">
                  {pedido.rua}, {pedido.numero}{f" — {pedido.complemento}" if pedido.complemento else ""}<br>
                  {pedido.bairro} — {pedido.cidade}/{pedido.estado}<br>
                  CEP {pedido.cep}
                </p>
              </div>

              <div style="text-align:center;padding:20px 0;border-top:1px solid #D9D3C7">
                <p style="font-size:13px;color:#9E9488;margin:0 0 16px">Dúvidas? Fale conosco pelo WhatsApp</p>
                <a href="https://wa.me/5511913225256" style="display:inline-block;padding:12px 28px;background:#25d366;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">💬 WhatsApp</a>
              </div>
            </div>
            <div style="background:#F5F2EC;padding:20px 40px;text-align:center">
              <p style="font-size:12px;color:#9E9488;margin:0">© 2026 Barrs Store • barrsstore.com.br</p>
            </div>
          </div>
        </body>
        </html>
        """

        token = os.environ.get('BREVO_API_KEY', '')
        http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'api-key': token,
                'Content-Type': 'application/json',
            },
            json={
                'sender': {'name': 'Barrs Store', 'email': 'contato.barrsstore@gmail.com'},
                'to': [{'email': pedido.email, 'name': pedido.nome}],
                'subject': f'📦 Seu pedido #{pedido.id} foi enviado! Código de rastreio dentro',
                'htmlContent': html,
            },
            timeout=10,
        )
        return True
    except Exception:
        return False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'email', 'cidade', 'status', 'total', 'rastreio_tag', 'criado_em')
    list_editable = ('status',)
    list_filter = ('status', 'forma_pagamento', 'estado')
    search_fields = ('nome', 'email', 'cidade', 'codigo_rastreio')
    readonly_fields = ('criado_em', 'email_rastreio_enviado')

    fieldsets = (
        ('Dados do pedido', {
            'fields': ('cliente', 'nome', 'email', 'telefone', 'status', 'forma_pagamento', 'criado_em')
        }),
        ('Valores', {
            'fields': ('subtotal', 'frete', 'total')
        }),
        ('Endereço de entrega', {
            'fields': ('cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado')
        }),
        ('📦 Rastreio', {
            'fields': ('codigo_rastreio', 'email_rastreio_enviado'),
            'description': '⚡ Ao salvar com um código de rastreio novo, o cliente receberá um email automaticamente!'
        }),
    )

    def rastreio_tag(self, obj):
        if obj.codigo_rastreio:
            return format_html('<span style="color:green;font-weight:bold">✓ {}</span>', obj.codigo_rastreio)
        return format_html('<span style="color:#ccc">—</span>')
    rastreio_tag.short_description = '📦 Rastreio'

    def save_model(self, request, obj, form, change):
        # Se adicionou código de rastreio e ainda não enviou o email
        if obj.codigo_rastreio and not obj.email_rastreio_enviado:
            super().save_model(request, obj, form, change)
            sucesso = enviar_email_rastreio(obj)
            if sucesso:
                obj.email_rastreio_enviado = True
                obj.save()
                # Mudar status para enviado automaticamente
                if obj.status == 'confirmado':
                    obj.status = 'enviado'
                    obj.save()
                messages.success(request, f'✅ Email de rastreio enviado para {obj.email}!')
            else:
                messages.warning(request, '⚠️ Código salvo, mas não foi possível enviar o email.')
        else:
            super().save_model(request, obj, form, change)


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
