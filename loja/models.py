from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal


# ── CONFIGURAÇÃO DE FRETE POR REGIÃO ──────────────────────────────
# Para alterar os valores, mude apenas os números abaixo:

# São Paulo (capital e Grande SP) — CEPs 01000-000 a 09999-999
FRETE_SP = Decimal('9.90')
FRETE_GRATIS_SP = Decimal('79.00')

# Regiões caras: Norte (AM, RR, AC, AP, PA, TO, RO)
FRETE_NORTE = Decimal('21.90')
FRETE_GRATIS_NORTE = Decimal('149.00')

# Resto do Brasil
FRETE_BRASIL = Decimal('16.90')
FRETE_GRATIS_BRASIL = Decimal('119.00')

# Estados da região Norte
ESTADOS_NORTE = ['AM', 'RR', 'AC', 'AP', 'PA', 'TO', 'RO']


def calcular_frete_por_estado(estado, subtotal):
    """Retorna (valor_frete, minimo_gratis) baseado no estado."""
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


class Produto(models.Model):
    nome = models.CharField(max_length=100)
    descricao = models.TextField(blank=True, default='')
    preco = models.DecimalField(max_digits=10, decimal_places=2)
    imagem = models.ImageField(upload_to='produtos/', null=True, blank=True)
    estoque = models.IntegerField(default=10)
    destaque = models.BooleanField(default=False)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nome

    def disponivel(self):
        return self.estoque > 0


class Carrinho(models.Model):
    criado_em = models.DateTimeField(auto_now_add=True)

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


class ItemCarrinho(models.Model):
    carrinho = models.ForeignKey(Carrinho, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    quantidade = models.IntegerField(default=1)

    def subtotal(self):
        return self.produto.preco * self.quantidade


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
    frete = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Pedido #{self.id} — {self.nome}'


class ItemPedido(models.Model):
    pedido = models.ForeignKey(Pedido, related_name='itens', on_delete=models.CASCADE)
    produto = models.ForeignKey(Produto, on_delete=models.SET_NULL, null=True)
    nome_produto = models.CharField(max_length=100)
    quantidade = models.IntegerField(default=1)
    preco_unitario = models.DecimalField(max_digits=10, decimal_places=2)

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
