from django.contrib import admin
from django import forms
from django.utils.html import format_html, format_html_join
from django.contrib import messages
from .models import (
    Produto, Carrinho, ItemCarrinho, Pedido, Categoria, TamanhoAnel, Cupom, EmailPendente,
    DispositivoTOTP, TokenEmergencia,
)


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
    change_list_template = 'admin/loja/produto/change_list.html'
    list_display = ('nome', 'categoria', 'tipo', 'preco', 'estoque', 'cliques', 'visivel', 'destaque')
    list_editable = ('preco', 'estoque', 'visivel', 'destaque')
    list_filter = ('visivel', 'destaque', 'categoria', 'tipo')
    search_fields = ('nome', 'descricao', 'slug')
    prepopulated_fields = {'slug': ('nome',)}
    readonly_fields = ('cliques',)
    fieldsets = (
        ('Produto', {
            'fields': ('nome', 'slug', 'descricao', 'preco', 'imagem', 'imagem_2', 'imagem_3', 'estoque', 'visivel', 'destaque', 'categoria', 'tipo')
        }),
        ('SEO', {
            'fields': ('meta_description', 'imagem_alt')
        }),
        ('Controle interno', {
            'fields': ('codigo_interno', 'estoque_proprio', 'cliques')
        }),
    )
    inlines = [TamanhoInline]

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['top_produtos_cliques'] = Produto.objects.filter(
            cliques__gt=0
        ).order_by('-cliques', 'nome')[:5]
        return super().changelist_view(request, extra_context=extra_context)


class PedidoAdminForm(forms.ModelForm):
    enviar_email_rastreio_agora = forms.BooleanField(
        required=False,
        label='Enviar e-mail de rastreio agora',
        help_text='Marque esta opção ao preencher ou alterar o código de rastreio.'
    )

    class Meta:
        model = Pedido
        fields = '__all__'


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    form = PedidoAdminForm
    list_display = ('id', 'nome', 'email', 'cpf', 'cidade', 'status', 'total', 'melhor_envio_order_id', 'codigo_rastreio', 'criado_em')
    list_editable = ('status',)
    list_filter = ('status', 'forma_pagamento', 'estado')
    search_fields = ('nome', 'email', 'cpf', 'cidade', 'codigo_rastreio', 'melhor_envio_order_id')
    readonly_fields = (
        'resumo_itens_admin',
        'criado_em',
        'access_token',
        'email_rastreio_enviado',
        'melhor_envio_order_id',
        'melhor_envio_status',
        'melhor_envio_erro',
    )
    fieldsets = (
        ('Resumo do pedido', {
            'fields': ('resumo_itens_admin',)
        }),
        ('Cliente', {
            'fields': ('cliente', 'nome', 'email', 'telefone', 'cpf')
        }),
        ('Endereço de entrega', {
            'fields': ('cep', 'rua', 'numero', 'complemento', 'bairro', 'cidade', 'estado')
        }),
        ('Pagamento', {
            'fields': ('forma_pagamento', 'status', 'subtotal', 'desconto', 'cupom_codigo', 'frete', 'total')
        }),
        ('Rastreio e Melhor Envio', {
            'fields': (
                'codigo_rastreio',
                'enviar_email_rastreio_agora',
                'email_rastreio_enviado',
                'melhor_envio_service_id',
                'melhor_envio_order_id',
                'melhor_envio_status',
                'melhor_envio_erro',
            )
        }),
        ('Controle interno', {
            'fields': ('access_token', 'criado_em')
        }),
    )

    @admin.display(description='Itens comprados')
    def resumo_itens_admin(self, obj):
        if not obj.pk:
            return 'Salve o pedido para ver os itens.'

        itens = obj.itens.select_related('produto').all()
        if not itens:
            return 'Nenhum item encontrado para este pedido.'

        linhas = format_html_join(
            '',
            '<tr>'
            '<td style="padding:8px;border-bottom:1px solid #ddd">{}</td>'
            '<td style="padding:8px;border-bottom:1px solid #ddd">{}</td>'
            '<td style="padding:8px;border-bottom:1px solid #ddd;text-align:center">{}</td>'
            '<td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">R$ {}</td>'
            '<td style="padding:8px;border-bottom:1px solid #ddd;text-align:right">R$ {}</td>'
            '</tr>',
            (
                (
                    item.nome_produto,
                    item.produto.codigo_interno if item.produto and item.produto.codigo_interno else 'Sem código',
                    item.quantidade,
                    item.preco_unitario,
                    item.subtotal(),
                )
                for item in itens
            )
        )

        return format_html(
            '<table style="width:100%;border-collapse:collapse;background:#fff">'
            '<thead>'
            '<tr style="background:#f5f5f5">'
            '<th style="padding:8px;text-align:left;border-bottom:1px solid #ddd">Produto</th>'
            '<th style="padding:8px;text-align:left;border-bottom:1px solid #ddd">Código</th>'
            '<th style="padding:8px;text-align:center;border-bottom:1px solid #ddd">Qtd</th>'
            '<th style="padding:8px;text-align:right;border-bottom:1px solid #ddd">Preço unitário</th>'
            '<th style="padding:8px;text-align:right;border-bottom:1px solid #ddd">Subtotal</th>'
            '</tr>'
            '</thead>'
            '<tbody>{}</tbody>'
            '<tfoot>'
            '<tr>'
            '<td colspan="4" style="padding:10px;text-align:right;font-weight:700">Total do pedido</td>'
            '<td style="padding:10px;text-align:right;font-weight:700">R$ {}</td>'
            '</tr>'
            '</tfoot>'
            '</table>',
            linhas,
            obj.total,
        )

    def save_model(self, request, obj, form, change):
        codigo_anterior = ''
        status_anterior = ''
        if change and obj.pk:
            antigo = Pedido.objects.filter(pk=obj.pk).first()
            if antigo:
                codigo_anterior = antigo.codigo_rastreio
                status_anterior = antigo.status

        enviar_rastreio = form.cleaned_data.get('enviar_email_rastreio_agora')
        super().save_model(request, obj, form, change)

        if obj.status == 'confirmado' and status_anterior != 'confirmado':
            try:
                from .views import criar_envio_melhor_envio
                if criar_envio_melhor_envio(obj):
                    self.message_user(request, 'Envio criado no Melhor Envio.', messages.SUCCESS)
                else:
                    self.message_user(request, 'Pedido confirmado, mas o Melhor Envio não gerou etiqueta. Veja o campo de erro.', messages.WARNING)
            except Exception as exc:
                self.message_user(request, f'Erro ao criar envio no Melhor Envio: {exc}', messages.ERROR)

        if not enviar_rastreio:
            return

        if not obj.codigo_rastreio:
            self.message_user(request, 'Preencha o código de rastreio antes de enviar o e-mail.', messages.WARNING)
            return

        codigo_alterado = codigo_anterior and codigo_anterior != obj.codigo_rastreio
        if obj.email_rastreio_enviado and not codigo_alterado:
            self.message_user(request, 'Este e-mail de rastreio já foi enviado para este código.', messages.WARNING)
            return

        try:
            from .views import enviar_email_rastreio
            if enviar_email_rastreio(obj):
                obj.email_rastreio_enviado = True
                if obj.status == 'confirmado':
                    obj.status = 'enviado'
                obj.save(update_fields=['email_rastreio_enviado', 'status'])
                self.message_user(request, 'E-mail de rastreio enviado ao cliente.', messages.SUCCESS)
            else:
                self.message_user(request, 'Não foi possível enviar o e-mail de rastreio. Veja os logs.', messages.ERROR)
        except Exception as exc:
            self.message_user(request, f'Erro ao enviar e-mail de rastreio: {exc}', messages.ERROR)


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
    list_display = ('id', 'telefone_cliente', 'aceita_whatsapp', 'whatsapp_abandono_enviado', 'criado_em', 'atualizado_em')
    list_filter = ('aceita_whatsapp', 'whatsapp_abandono_enviado')
    search_fields = ('telefone_cliente',)


@admin.register(EmailPendente)
class EmailPendenteAdmin(admin.ModelAdmin):
    list_display = ('id', 'assunto', 'destinatario_email', 'status', 'tentativas', 'criado_em', 'enviado_em')
    list_filter = ('status', 'criado_em')
    search_fields = ('assunto', 'destinatario_email')
    readonly_fields = ('dedupe_key', 'payload', 'tentativas', 'ultimo_erro', 'criado_em', 'atualizado_em', 'enviado_em')


# ── 2FA: re-registra OTP com nomes em portugues ───────────────────
from django_otp.plugins.otp_totp.admin import TOTPDeviceAdmin
from django_otp.plugins.otp_static.admin import StaticDeviceAdmin
from django_otp.plugins.otp_totp.models import TOTPDevice as _TOTPDeviceModel
from django_otp.plugins.otp_static.models import StaticDevice as _StaticDeviceModel

try:
    admin.site.unregister(_TOTPDeviceModel)
except admin.sites.NotRegistered:
    pass
try:
    admin.site.unregister(_StaticDeviceModel)
except admin.sites.NotRegistered:
    pass


_LABELS_PT_TOTP = {
    'user': ('Usuário', 'O usuário ao qual este dispositivo pertence.'),
    'name': ('Nome', 'Nome amigável para identificar o dispositivo (ex.: Meu celular).'),
    'confirmed': ('Confirmado', 'Marque para indicar que este dispositivo está pronto para uso.'),
    'key': ('Chave secreta', 'Chave hexadecimal usada para gerar os códigos. Não compartilhe.'),
    'step': ('Intervalo (segundos)', 'Tempo de vida de cada código (padrão 30s).'),
    't0': ('Tempo de referência (T0)', 'Timestamp Unix inicial da contagem. Padrão 0.'),
    'digits': ('Quantidade de dígitos', 'Tamanho do código gerado (6 ou 8).'),
    'tolerance': ('Tolerância', 'Quantos passos antes/depois também são aceitos (recomendado 1).'),
    'drift': ('Desvio', 'Desvio atual do relógio do dispositivo (em passos).'),
    'last_t': ('Último passo usado', 'Último intervalo aceito; previne reuso do mesmo código.'),
    'throttling_failure_count': ('Falhas consecutivas', 'Tentativas malsucedidas seguidas. Zera no acerto.'),
    'last_used_at': ('Último uso', 'Quando foi usado pela última vez.'),
    'created_at': ('Criado em', 'Data de criação do dispositivo.'),
}

_LABELS_PT_STATIC = {
    'user': ('Usuário', 'O usuário ao qual este token pertence.'),
    'name': ('Nome', 'Nome amigável para identificar o conjunto de tokens.'),
    'confirmed': ('Confirmado', 'Marque para indicar que este conjunto está pronto para uso.'),
    'throttling_failure_count': ('Falhas consecutivas', 'Tentativas malsucedidas seguidas.'),
}


def _aplicar_labels_pt(form, mapa):
    for nome, (label, help_text) in mapa.items():
        if nome in form.base_fields:
            form.base_fields[nome].label = label
            form.base_fields[nome].help_text = help_text
    return form


_TRADUCAO_FIELDSET = {
    'Identity': 'Identidade',
    'Timestamps': 'Datas',
    'Configuration': 'Configuração',
    'State': 'Estado',
    'Throttling': 'Bloqueio por tentativas',
}


def _traduzir_fieldsets(fieldsets):
    return [
        (_TRADUCAO_FIELDSET.get(nome, nome) if nome else nome, opts)
        for nome, opts in fieldsets
    ]


@admin.register(DispositivoTOTP)
class DispositivoTOTPAdmin(TOTPDeviceAdmin):
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        return _aplicar_labels_pt(form, _LABELS_PT_TOTP)

    def get_fieldsets(self, request, obj=None):
        return _traduzir_fieldsets(super().get_fieldsets(request, obj))


@admin.register(TokenEmergencia)
class TokenEmergenciaAdmin(StaticDeviceAdmin):
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        return _aplicar_labels_pt(form, _LABELS_PT_STATIC)

    def get_fieldsets(self, request, obj=None):
        return _traduzir_fieldsets(super().get_fieldsets(request, obj))
