from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.text import slugify
from decimal import Decimal
import uuid


# ── CONFIGURAÇÃO DE FRETE POR REGIÃO ──────────────────────────────
FRETE_SP = Decimal('9.90')
FRETE_GRATIS_SP = Decimal('79.00')
FRETE_NORTE = Decimal('21.90')
FRETE_GRATIS_NORTE = Decimal('149.00')
FRETE_BRASIL = Decimal('16.90')
FRETE_GRATIS_BRASIL = Decimal('119.00')
ESTADOS_NORTE = ['AM', 'RR', 'AC', 'AP', 'PA', 'TO', 'RO']


def calcular_frete_por_estado(estado, subtotal):
    estado = (estado or '').upper().strip()
    if estado == 'SP':
        valor = FRETE_SP
        minimo = FRETE_GRATIS_SP
    elif estado in ESTADOS_NORTE:
        valor = FRETE_NORTE
        minimo = FRETE_GRATIS_NORTE
    else:
        valor = FRETE_BRASIL
        minimo = FRETE_GRATIS_BRASIL
    frete = Decimal('0') if subtotal >= minimo else valor
    return frete, minimo


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
    estoque = models.IntegerField(default=10)
    destaque = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, related_name='produtos')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='acessorio')
    codigo_interno = models.CharField(max_length=50, blank=True, default='', help_text='Código interno (só visível no admin)')
    estoque_proprio = models.BooleanField(default=True, help_text='Produto em estoque próprio? Se não, sob demanda.')

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
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('detalhe_produto', kwargs={'slug': self.slug})

    def seo_description(self):
        texto = self.meta_description or self.descricao or f'{self.nome} na Barrs Store.'
        return texto[:157] + '...' if len(texto) > 160 else texto

    def alt_text(self):
        return self.imagem_alt or self.nome

    def disponivel(self):
        return self.estoque > 0

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
    telefone_cliente = models.CharField(max_length=20, blank=True, default='')
    aceita_whatsapp = models.BooleanField(default=False)
    whatsapp_abandono_enviado = models.BooleanField(default=False)
    whatsapp_abandono_enviado_em = models.DateTimeField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    def total(self):
        return sum(item.subtotal() for item in self.itens.all())

    def quantidade_total(self):
        return sum(item.quantidade for item in self.itens.all())

    def frete(self, estado='SP'):
        frete, _ = calcular_frete_por_estado(estado, self.total())
        return frete

    def total_com_frete(self, estado='SP'):
        return self.total() + self.frete(estado)

    def frete_gratis(self, estado='SP'):
        return self.frete(estado) == Decimal('0')

    def falta_para_frete_gratis(self, estado='SP'):
        _, minimo = calcular_frete_por_estado(estado, self.total())
        falta = minimo - self.total()
        return max(falta, Decimal('0'))

    def minimo_frete_gratis(self, estado='SP'):
        _, minimo = calcular_frete_por_estado(estado, self.total())
        return minimo

    def link_checkout(self):
        from django.conf import settings

        base = getattr(settings, 'SITE_URL', 'https://www.barrsstore.com.br').rstrip('/')
        return f"{base}{reverse('finalizar_compra')}"


class ItemCarrinho(models.Model):
    carrinho = models.ForeignKey(Carrinho, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.IntegerField(default=1)
    tamanho = models.CharField(max_length=5, blank=True, default='')  # para anéis

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
    email = models.EmailField()
    telefone = models.CharField(max_length=20, blank=True, default='')
    cpf = models.CharField(max_length=14, blank=True, default='')
    cep = models.CharField(max_length=9)
    rua = models.CharField(max_length=200)
    numero = models.CharField(max_length=20)
    complemento = models.CharField(max_length=100, blank=True, default='')
    bairro = models.CharField(max_length=100)
    cidade = models.CharField(max_length=100)
    estado = models.CharField(max_length=2)
    forma_pagamento = models.CharField(max_length=20, choices=PAGAMENTO_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pendente')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    desconto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cupom_codigo = models.CharField(max_length=30, blank=True, default='')
    frete = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True)
    codigo_rastreio = models.CharField(max_length=100, blank=True, default='', help_text='Código de rastreio dos Correios')
    email_rastreio_enviado = models.BooleanField(default=False, help_text='Email de rastreio já foi enviado')
    melhor_envio_service_id = models.PositiveIntegerField(null=True, blank=True)
    melhor_envio_order_id = models.CharField(max_length=80, blank=True, default='')
    melhor_envio_status = models.CharField(max_length=40, blank=True, default='')
    melhor_envio_erro = models.TextField(blank=True, default='')
    access_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    email_confirmacao_enviado = models.BooleanField(default=False)
    email_pagamento_pendente_enviado = models.BooleanField(default=False)

    def __str__(self):
        return f'Pedido #{self.id} - {self.nome}'

    def rastreio_url(self):
        if not self.codigo_rastreio:
            return ''
        return f'https://rastreamento.correios.com.br/app/index.php?objeto={self.codigo_rastreio}'


class Cupom(models.Model):
    TIPO_CHOICES = [
        ('percentual', 'Percentual'),
        ('valor', 'Valor fixo'),
    ]

    codigo = models.CharField(max_length=30, unique=True)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='percentual')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    ativo = models.BooleanField(default=True)
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

    def valido_para(self, subtotal):
        if not self.ativo:
            return False, 'Cupom inativo.'
        if self.uso_maximo and self.usado >= self.uso_maximo:
            return False, 'Cupom esgotado.'
        if subtotal < self.valor_minimo:
            return False, f'Cupom valido para compras a partir de R$ {self.valor_minimo}.'
        return True, ''

    def calcular_desconto(self, subtotal):
        if self.tipo == 'percentual':
            desconto = subtotal * (self.valor / Decimal('100'))
        else:
            desconto = self.valor
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
