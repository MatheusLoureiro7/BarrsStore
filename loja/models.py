import json
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify
from django_otp.plugins.otp_static.models import StaticDevice as _StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice as _TOTPDevice

from .shipping import (
    calcular_frete_por_estado,
    ESTADOS_NORTE,
    FRETE_BRASIL,
    FRETE_GRATIS_BRASIL,
    FRETE_GRATIS_NORTE,
    FRETE_GRATIS_SP,
    FRETE_NORTE,
    FRETE_SP,
)


# ── CATEGORIA ─────────────────────────────────────────────────────
class Categoria(models.Model):
    nome = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    icone = models.CharField(max_length=10, blank=True, default='💎', help_text='Emoji do ícone')

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nome']

    def __str__(self):
        return self.nome


# ── PRODUTO ───────────────────────────────────────────────────────
class Produto(models.Model):
    TIPO_CHOICES = [
        ('acessorio', 'Acessório geral'),
        ('anel', 'Anel'),
        ('brinco', 'Brinco'),
        ('colar', 'Colar'),
        ('pulseira', 'Pulseira'),
        ('tornozeleira', 'Tornozeleira'),
    ]

    nome = models.CharField(max_length=100)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    descricao = models.TextField(blank=True, default='')
    meta_description = models.CharField(max_length=160, blank=True, default='', help_text='Resumo para Google, ate 160 caracteres')
    imagem_alt = models.CharField(max_length=120, blank=True, default='', help_text='Texto alternativo da imagem para SEO e acessibilidade')
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    imagem = models.ImageField(upload_to='produtos/', null=True, blank=True)
    imagem_2 = models.ImageField(upload_to='produtos/', null=True, blank=True)
    imagem_3 = models.ImageField(upload_to='produtos/', null=True, blank=True)
    estoque = models.IntegerField(default=10)
    visivel = models.BooleanField(default=True, help_text='Exibir este produto no site?')
    destaque = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='produtos')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='acessorio')
    codigo_interno = models.CharField(max_length=50, blank=True, default='', help_text='Código interno (só visível no admin)')
    estoque_proprio = models.BooleanField(default=True, help_text='Produto em estoque próprio? Se não, sob demanda.')
    cliques = models.PositiveIntegerField(default=0, help_text='Quantidade de acessos na pagina do produto.')
    peso_gramas = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Peso unitario da peca em gramas. Se vazio, usamos 8g como padrao no calculo de frete.',
    )

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Produto'
        verbose_name_plural = 'Produtos'
        indexes = [
            models.Index(fields=['visivel', '-criado_em']),
            models.Index(fields=['visivel', 'destaque']),
        ]

    def __str__(self):
        return self.nome

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.nome) or 'produto'
            slug = base_slug
            contador = 2
            while Produto.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{contador}'
                contador += 1
            self.slug = slug
        # Preenche SEO automatico apenas quando o admin nao definiu manualmente.
        if not self._clean_seo_text(self.meta_description):
            self.meta_description = self._auto_meta_description()
        if not self._clean_seo_text(self.imagem_alt):
            nome = self._clean_seo_text(self.nome) or 'Semijoia'
            self.imagem_alt = f'{nome} feminino da Barrs Store'
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('detalhe_produto', kwargs={'slug': self.slug})

    @staticmethod
    def _clean_seo_text(text):
        return ' '.join(strip_tags(str(text or '')).split())

    @staticmethod
    def _limit_seo_text(text, limit=160):
        text = Produto._clean_seo_text(text)
        if len(text) <= limit:
            return text
        shortened = text[:limit - 3].rsplit(' ', 1)[0].rstrip(',. ')
        return f'{shortened}...' if shortened else text[:limit - 3] + '...'

    @staticmethod
    def _normalized_text(text):
        return slugify(Produto._clean_seo_text(text)).replace('-', ' ')

    @staticmethod
    def _pick_by_name(nome, options):
        if not options:
            return ''
        seed = sum(ord(char) for char in Produto._clean_seo_text(nome).lower())
        return options[seed % len(options)]

    def _seo_category_key(self):
        parts = [self.tipo, self.nome]
        if self.categoria_id and self.categoria:
            parts.extend([self.categoria.nome, self.categoria.slug])
        text = self._normalized_text(' '.join(parts))
        for key in ('riviera', 'choker', 'colar', 'anel', 'pulseira', 'brinco'):
            if key in text:
                return key
        return ''

    def _seo_style_phrase(self):
        name = self._normalized_text(self.nome)
        if 'coracao' in name:
            return 'design romântico e brilho delicado'
        if 'perola' in name:
            return 'toque clássico e luminosidade suave'
        if 'flor' in name:
            return 'traços delicados e inspiração feminina'
        if 'dourado' in name or 'ouro' in name:
            return 'banho dourado e presença sofisticada'
        if 'prata' in name or 'prateado' in name:
            return 'brilho prateado e acabamento clean'
        if 'pedra' in name or 'zirconia' in name or 'ponto de luz' in name:
            return 'pontos de luz e brilho na medida'
        if 'gota' in name:
            return 'forma delicada e caimento elegante'
        return self._pick_by_name(self.nome, [
            'brilho delicado e presença discreta',
            'linhas leves e acabamento refinado',
            'visual moderno e toque feminino',
            'design clean para composições elegantes',
        ])

    def _auto_meta_description(self):
        nome = self._clean_seo_text(self.nome) or 'Peça Barrs Store'
        estilo = self._seo_style_phrase()
        category = self._seo_category_key()
        templates = {
            'colar': [
                f'{nome} com {estilo}. Ideal para valorizar decotes e compor looks modernos com um toque refinado.',
                f'{nome} traz {estilo} para produções delicadas, do dia a dia a ocasiões especiais.',
                f'Use {nome} para iluminar o colo com {estilo}, mantendo uma proposta feminina e atual.',
            ],
            'anel': [
                f'{nome} com {estilo}. Um detalhe marcante para mãos delicadas e combinações elegantes.',
                f'{nome} valoriza o visual com {estilo}, perfeito para usar sozinho ou em mix de anéis.',
                f'{nome} com {estilo}, pensado para adicionar charme sem pesar na composição.',
            ],
            'pulseira': [
                f'{nome} com {estilo}. Um toque delicado para o pulso e para combinações com relógios ou outras peças.',
                f'{nome} completa o look com {estilo}, em uma proposta leve para usar todos os dias.',
                f'{nome} com {estilo}, criada para trazer brilho sutil às produções femininas.',
            ],
            'brinco': [
                f'{nome} com {estilo}. Leve brilho ao rosto com uma peça delicada e fácil de combinar.',
                f'{nome} destaca o visual com {estilo}, perfeito para looks femininos e bem acabados.',
                f'{nome} com {estilo}, uma escolha charmosa para iluminar a produção.',
            ],
            'riviera': [
                f'{nome} com brilho contínuo e acabamento sofisticado. Uma peça de impacto para produções elegantes.',
                f'{nome} traz presença e luminosidade em uma composição clássica, perfeita para ocasiões especiais.',
                f'{nome} com brilho marcante e desenho refinado para elevar o visual com sofisticação.',
            ],
            'choker': [
                f'{nome} com {estilo}. Uma choker moderna para destacar o colo com delicadeza.',
                f'{nome} combina presença e leveza, ideal para looks atuais com um toque sofisticado.',
                f'{nome} com {estilo}, perfeita para composições femininas e modernas.',
            ],
        }
        fallback = [
            f'{nome} com {estilo}. Uma escolha delicada para completar o look com brilho na medida.',
            f'{nome} une beleza e leveza em uma peça fácil de combinar em diferentes ocasiões.',
            f'{nome} traz um toque refinado para produções femininas, com visual clean e atual.',
        ]
        return self._limit_seo_text(self._pick_by_name(nome, templates.get(category, fallback)))

    def get_seo_title(self):
        nome = self._clean_seo_text(self.nome) or 'Semijoia'
        return f'{nome} | Barrs Store'

    def get_meta_description(self):
        if self.meta_description:
            return self._limit_seo_text(self.meta_description)
        return self._auto_meta_description()

    def get_image_alt(self):
        if self.imagem_alt:
            return self._clean_seo_text(self.imagem_alt)
        nome = self._clean_seo_text(self.nome) or 'Semijoia'
        return f'{nome} feminino da Barrs Store'

    def get_og_title(self):
        return self.get_seo_title()

    def get_og_description(self):
        return self.get_meta_description()

    def get_schema_json_ld(self, absolute_url='', absolute_image_url=''):
        nome = self._clean_seo_text(self.nome) or 'Semijoia Barrs Store'
        schema = {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': nome,
            'description': self.get_meta_description(),
            'sku': str(self.id or ''),
            'brand': {
                '@type': 'Brand',
                'name': 'Barrs Store',
            },
            'offers': {
                '@type': 'Offer',
                'price': str(self.preco or Decimal('0.00')),
                'priceCurrency': 'BRL',
                'availability': 'https://schema.org/InStock' if self.disponivel() else 'https://schema.org/OutOfStock',
                'url': absolute_url or self.get_absolute_url(),
            },
        }
        if absolute_image_url:
            schema['image'] = [absolute_image_url]
        if self.categoria_id and self.categoria:
            schema['category'] = self._clean_seo_text(self.categoria.nome)
        return (
            json.dumps(schema, ensure_ascii=False)
            .replace('&', '\\u0026')
            .replace('<', '\\u003C')
            .replace('>', '\\u003E')
        )

    def seo_description(self):
        return self.get_meta_description()

    def alt_text(self):
        return self.get_image_alt()

    def disponivel(self):
        return self.estoque > 0

    def is_novo(self):
        if not self.criado_em:
            return False
        return self.criado_em >= timezone.now() - timezone.timedelta(days=14)

    def estoque_baixo(self):
        return 0 < self.estoque < 3

    def tem_tamanhos(self):
        return self.tipo == 'anel'

    def tamanhos_disponiveis(self):
        return self.tamanhos.filter(estoque__gt=0).order_by('numero')


# ── TAMANHO (só para anéis) ────────────────────────────────────────
class TamanhoAnel(models.Model):
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE, related_name='tamanhos')
    numero = models.CharField(max_length=5, help_text='Ex: 14, 15, 16, 17, 18')
    estoque = models.IntegerField(default=5)

    class Meta:
        ordering = ['numero']
        verbose_name = 'Tamanho'
        verbose_name_plural = 'Tamanhos'

    def __str__(self):
        return f'{self.produto.nome} — Nº {self.numero}'


# ── CARRINHO ──────────────────────────────────────────────────────
class Carrinho(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True)
    nome_cliente = models.CharField(max_length=100, blank=True, default='')
    telefone_cliente = models.CharField(max_length=20, blank=True, default='')
    email_cliente = models.EmailField(blank=True, default='')
    aceita_whatsapp = models.BooleanField(default=False)
    whatsapp_abandono_enviado = models.BooleanField(default=False)
    whatsapp_abandono_enviado_em = models.DateTimeField(null=True, blank=True)
    email_abandono_1_enviado = models.BooleanField(default=False)
    email_abandono_2_enviado = models.BooleanField(default=False)
    email_abandono_3_enviado = models.BooleanField(default=False)
    atualizado_em = models.DateTimeField(auto_now=True, db_index=True)

    def total(self):
        # select_related evita N+1 ao acessar item.produto.preco em item.subtotal().
        return sum(item.subtotal() for item in self.itens.select_related('produto').all())

    def quantidade_total(self):
        return sum(item.quantidade for item in self.itens.all())

    def link_checkout(self):
        from django.conf import settings

        base = getattr(settings, 'SITE_URL', 'https://www.barrsstore.com.br').rstrip('/')
        return f"{base}{reverse('finalizar_compra')}"


class ItemCarrinho(models.Model):
    carrinho = models.ForeignKey(Carrinho, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.IntegerField(default=1)
    tamanho = models.CharField(max_length=5, blank=True, default='')  # para anéis

    class Meta:
        unique_together = [('carrinho', 'produto', 'tamanho')]
        verbose_name = 'Item do carrinho'
        verbose_name_plural = 'Itens do carrinho'

    def subtotal(self):
        return self.produto.preco * self.quantidade


# ── PEDIDO ────────────────────────────────────────────────────────
class Pedido(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('confirmado', 'Confirmado'),
        ('enviado', 'Enviado'),
        ('entregue', 'Entregue'),
        ('cancelado', 'Cancelado'),
    ]

    PAGAMENTO_CHOICES = [
        ('pix', 'PIX'),
        ('cartao', 'Cartão de crédito'),
        ('boleto', 'Boleto bancário'),
    ]

    cliente = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos')
    nome = models.CharField(max_length=100)
    email = models.EmailField(db_index=True)
    telefone = models.CharField(max_length=20, blank=True, default='')
    cpf = models.CharField(max_length=14, blank=True, default='')
    cep = models.CharField(max_length=9)
    rua = models.CharField(max_length=200)
    numero = models.CharField(max_length=20)
    complemento = models.CharField(max_length=100, blank=True, default='')
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    estado = models.CharField(max_length=2)
    forma_pagamento = models.CharField(max_length=20, choices=PAGAMENTO_CHOICES, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente', db_index=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cupom_codigo = models.CharField(max_length=30, blank=True, default='')
    frete = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    codigo_rastreio = models.CharField(max_length=100, blank=True, default='', help_text='Código de rastreio dos Correios')
    email_rastreio_enviado = models.BooleanField(default=False, help_text='Email de rastreio já foi enviado')
    melhor_envio_service_id = models.PositiveIntegerField(null=True, blank=True)
    melhor_envio_order_id = models.CharField(max_length=80, blank=True, default='')
    melhor_envio_status = models.CharField(max_length=40, blank=True, default='')
    melhor_envio_erro = models.TextField(blank=True, default='')
    access_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email_confirmacao_enviado = models.BooleanField(default=False)
    email_pagamento_pendente_enviado = models.BooleanField(default=False)
    email_poscompra_1_enviado = models.BooleanField(default=False)
    email_poscompra_2_enviado = models.BooleanField(default=False)
    email_poscompra_3_enviado = models.BooleanField(default=False)
    email_poscompra_4_enviado = models.BooleanField(default=False)
    email_poscompra_5_enviado = models.BooleanField(default=False)
    estoque_baixado = models.BooleanField(default=False)
    meta_purchase_sent = models.BooleanField(default=False)
    # Atribuição: UTM e gclid/fbclid capturados no momento do pedido (last-touch).
    origem_utm = models.JSONField(default=dict, blank=True, help_text='Parâmetros utm_*, gclid e fbclid da última visita.')
    observacoes = models.CharField(max_length=500, blank=True, default='', help_text='Instruções do cliente: embrulho de presente, observações de entrega, etc.')

    def __str__(self):
        return f'Pedido #{self.id} - {self.nome}'

    def rastreio_url(self):
        if not self.codigo_rastreio:
            return ''
        if self.melhor_envio_service_id == 31:
            return 'https://www.loggi.com/rastreador/'
        return f'https://rastreamento.correios.com.br/app/index.php?objeto={self.codigo_rastreio}'

    def rastreio_transportadora(self):
        if self.melhor_envio_service_id == 31:
            return 'Loggi'
        if self.melhor_envio_service_id in (1, 2):
            return 'Correios'
        return 'transportadora'


class Cupom(models.Model):
    TIPO_CHOICES = [
        ('percentual', 'Percentual'),
        ('valor', 'Valor fixo'),
        ('frete_gratis', 'Frete grátis'),
    ]

    codigo = models.CharField(max_length=30, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='percentual')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    ativo = models.BooleanField(default=True)
    so_clientes_fidelidade = models.BooleanField(default=False, help_text='Somente para clientes com pelo menos 1 pedido confirmado.')
    uso_maximo = models.PositiveIntegerField(default=0, help_text='0 = sem limite')
    usado = models.PositiveIntegerField(default=0)
    valor_minimo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Cupom'
        verbose_name_plural = 'Cupons'

    def __str__(self):
        return self.codigo.upper()

    def valido_para(self, subtotal, user=None):
        if not self.ativo:
            return False, 'Cupom inativo.'
        if self.uso_maximo and self.usado >= self.uso_maximo:
            return False, 'Cupom esgotado.'
        if subtotal < self.valor_minimo:
            return False, f'Cupom valido para compras a partir de R$ {self.valor_minimo}.'
        if self.so_clientes_fidelidade:
            if not user or not getattr(user, 'is_authenticated', False):
                return False, 'Este cupom e exclusivo para clientes com compras anteriores. Faca login para continuar.'
            tem_pedido = user.pedidos.filter(status__in=['confirmado', 'enviado', 'entregue']).exists()
            if not tem_pedido:
                return False, 'Este cupom e exclusivo para quem ja realizou uma compra na Barrs Store.'
        return True, ''

    def calcular_desconto(self, subtotal, frete=Decimal('0')):
        if self.tipo == 'frete_gratis':
            valor_frete = frete if isinstance(frete, Decimal) else Decimal(str(frete or 0))
            return valor_frete.quantize(Decimal('0.01'))
        if self.tipo == 'percentual':
            desconto = subtotal * (self.valor / Decimal('100'))
        else:
            desconto = self.valor if isinstance(self.valor, Decimal) else Decimal(str(self.valor))
        return min(desconto.quantize(Decimal('0.01')), subtotal)


class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.SET_NULL, null=True)
    nome_produto = models.CharField(max_length=100)
    quantidade = models.IntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    tamanho = models.CharField(max_length=5, blank=True, default='')

    def subtotal(self):
        return self.preco_unitario * self.quantidade

    def __str__(self):
        return f'{self.quantidade}x {self.nome_produto}'


class PerfilCliente(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    telefone = models.CharField(max_length=20, blank=True, default='')
    cep = models.CharField(max_length=9, blank=True, default='')
    rua = models.CharField(max_length=200, blank=True, default='')
    numero = models.CharField(max_length=20, blank=True, default='')
    complemento = models.CharField(max_length=100, blank=True, default='')
    bairro = models.CharField(max_length=100, blank=True, default='')
    cidade = models.CharField(max_length=100, blank=True, default='')
    estado = models.CharField(max_length=2, blank=True, default='')

    def __str__(self):
        return f'Perfil de {self.user.email}'


class EmailPendente(models.Model):
    STATUS_CHOICES = [
        ('pendente', 'Pendente'),
        ('enviado', 'Enviado'),
        ('erro', 'Erro'),
    ]

    dedupe_key = models.CharField(max_length=64, unique=True)
    destinatario_email = models.EmailField()
    destinatario_nome = models.CharField(max_length=120, blank=True, default='')
    assunto = models.CharField(max_length=200)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    tentativas = models.PositiveIntegerField(default=0)
    ultimo_erro = models.TextField(blank=True, default='')
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['criado_em']
        verbose_name = 'E-mail pendente'
        verbose_name_plural = 'E-mails pendentes'
        indexes = [
            models.Index(fields=['status', 'criado_em']),
        ]

    def __str__(self):
        return f'{self.assunto} -> {self.destinatario_email}'


# ── LEAD (captura via popup da home) ──────────────────────────────
class Lead(models.Model):
    nome = models.CharField(max_length=120)
    telefone = models.CharField(max_length=20)
    aceita_whatsapp = models.BooleanField(default=True)
    origem = models.CharField(max_length=50, default='home')
    criado_em = models.DateTimeField(auto_now_add=True)
    sessao_key = models.CharField(max_length=40, blank=True, null=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'
        indexes = [
            models.Index(fields=['sessao_key', 'telefone']),
        ]

    def __str__(self):
        return f'{self.nome} ({self.telefone})'


# ── PROXIES PARA TRADUZIR django-otp NO ADMIN ─────────────────────
class DispositivoTOTP(_TOTPDevice):
    class Meta:
        proxy = True
        app_label = 'loja'
        verbose_name = 'Dispositivo TOTP (2FA)'
        verbose_name_plural = 'Dispositivos TOTP (2FA)'


class TokenEmergencia(_StaticDevice):
    class Meta:
        proxy = True
        app_label = 'loja'
        verbose_name = 'Token de emergência'
        verbose_name_plural = 'Tokens de emergência'
