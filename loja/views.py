from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from .models import Produto, Carrinho, ItemCarrinho, Pedido


# ── HELPER: dados do carrinho para navbar ──────────────────────────
def get_carrinho_info(request):
    carrinho_id = request.session.get('carrinho_id')
    qtd_carrinho = 0
    if carrinho_id:
        try:
            carrinho = Carrinho.objects.get(id=carrinho_id)
            qtd_carrinho = sum(item.quantidade for item in carrinho.itens.all())
        except Carrinho.DoesNotExist:
            pass
    return qtd_carrinho


# ── HOME ───────────────────────────────────────────────────────────
def home(request):
    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')

    produtos = Produto.objects.all()

    if busca:
        produtos = produtos.filter(
            Q(nome__icontains=busca) | Q(descricao__icontains=busca)
        )

    if ordem == 'menor':
        produtos = produtos.order_by('preco')
    elif ordem == 'maior':
        produtos = produtos.order_by('-preco')
    elif ordem == 'nome':
        produtos = produtos.order_by('nome')
    else:
        produtos = produtos.order_by('-criado_em')

    return render(request, 'home.html', {
        'produtos': produtos,
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': Produto.objects.count(),
    })


# ── DETALHE DO PRODUTO ─────────────────────────────────────────────
def detalhe_produto(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    relacionados = Produto.objects.exclude(id=produto_id)[:4]
    return render(request, 'detalhe.html', {
        'produto': produto,
        'relacionados': relacionados,
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── CARRINHO ───────────────────────────────────────────────────────
def ver_carrinho(request):
    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return render(request, 'carrinho.html', {
            'itens': [],
            'total': 0,
            'qtd_carrinho': 0,
        })

    carrinho = Carrinho.objects.get(id=carrinho_id)
    return render(request, 'carrinho.html', {
        'itens': carrinho.itens.all(),
        'total': carrinho.total(),
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── ADICIONAR AO CARRINHO ──────────────────────────────────────────
def adicionar_carrinho(request, produto_id):
    produto = get_object_or_404(Produto, id=produto_id)
    carrinho_id = request.session.get('carrinho_id')

    if carrinho_id:
        try:
            carrinho = Carrinho.objects.get(id=carrinho_id)
        except Carrinho.DoesNotExist:
            carrinho = Carrinho.objects.create()
            request.session['carrinho_id'] = carrinho.id
    else:
        carrinho = Carrinho.objects.create()
        request.session['carrinho_id'] = carrinho.id

    item, criado = ItemCarrinho.objects.get_or_create(
        carrinho=carrinho,
        produto=produto
    )

    if not criado:
        item.quantidade += 1
        item.save()

    # Redireciona de volta para onde veio
    next_url = request.GET.get('next', 'carrinho')
    if next_url == 'detalhe':
        return redirect('detalhe_produto', produto_id=produto_id)
    return redirect('carrinho')


# ── REMOVER 1 UNIDADE ──────────────────────────────────────────────
def remover_item(request, item_id):
    item = get_object_or_404(ItemCarrinho, id=item_id)
    if item.quantidade > 1:
        item.quantidade -= 1
        item.save()
    else:
        item.delete()
    return redirect('carrinho')


# ── DELETAR ITEM INTEIRO ───────────────────────────────────────────
def deletar_item(request, item_id):
    item = get_object_or_404(ItemCarrinho, id=item_id)
    item.delete()
    return redirect('carrinho')


# ── CHECKOUT ───────────────────────────────────────────────────────
def checkout(request):
    carrinho_id = request.session.get('carrinho_id')
    if not carrinho_id:
        return redirect('carrinho')

    carrinho = get_object_or_404(Carrinho, id=carrinho_id)
    itens = carrinho.itens.all()

    if not itens:
        return redirect('carrinho')

    if request.method == 'POST':
        pedido = Pedido.objects.create(
            nome=request.POST['nome'],
            email=request.POST['email'],
            telefone=request.POST.get('telefone', ''),
            cep=request.POST['cep'],
            rua=request.POST['rua'],
            numero=request.POST['numero'],
            complemento=request.POST.get('complemento', ''),
            bairro=request.POST['bairro'],
            cidade=request.POST['cidade'],
            estado=request.POST['estado'],
            forma_pagamento=request.POST['forma_pagamento'],
            total=carrinho.total(),
        )

        carrinho.delete()
        del request.session['carrinho_id']

        return redirect('confirmacao', pedido_id=pedido.id)

    return render(request, 'checkout.html', {
        'itens': itens,
        'total': carrinho.total(),
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── CONFIRMAÇÃO ────────────────────────────────────────────────────
def confirmacao(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    return render(request, 'confirmacao.html', {'pedido': pedido})


# ── 404 CUSTOMIZADO ────────────────────────────────────────────────
def pagina_404(request, exception):
    return render(request, '404.html', status=404)


def sobre(request):
    return render(request, 'sobre.html', {'qtd_carrinho': get_carrinho_info(request)})


def contato(request):
    return render(request, 'contato.html', {'qtd_carrinho': get_carrinho_info(request)})


def politica(request):
    return render(request, 'politica.html')
