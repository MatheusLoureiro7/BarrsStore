from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from .models import Produto, Carrinho, ItemCarrinho, Pedido, ItemPedido
import mercadopago
import json


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

        # Salva os itens no pedido antes de deletar o carrinho
        for item in itens:
            ItemPedido.objects.create(
                pedido=pedido,
                produto=item.produto,
                nome_produto=item.produto.nome,
                quantidade=item.quantidade,
                preco_unitario=item.produto.preco,
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
    return render(request, 'confirmacao.html', {
        'pedido': pedido,
        'mp_public_key': settings.MERCADOPAGO_PUBLIC_KEY,
    })


# ── MERCADO PAGO: CRIAR PREFERÊNCIA ───────────────────────────────
def criar_preferencia(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

    items = []
    for item in pedido.itens.all():
        items.append({
            "title": item.nome_produto,
            "quantity": int(item.quantidade),
            "unit_price": float(item.preco_unitario),
            "currency_id": "BRL",
        })

    preference_data = {
        "items": items,
        "payer": {
            "name": pedido.nome,
            "email": pedido.email,
            "phone": {"number": pedido.telefone},
        },
        "back_urls": {
            "success": f"https://www.barrsstore.com.br/pagamento/sucesso/{pedido.id}/",
            "failure": f"https://www.barrsstore.com.br/pagamento/falha/{pedido.id}/",
            "pending": f"https://www.barrsstore.com.br/pagamento/pendente/{pedido.id}/",
        },
        "auto_return": "approved",
        "external_reference": str(pedido.id),
        "statement_descriptor": "BARRS STORE",
    }

    preference_response = sdk.preference().create(preference_data)
    preference = preference_response["response"]

    return JsonResponse({
        "preference_id": preference["id"],
        "init_point": preference["init_point"],
    })


# ── MERCADO PAGO: RETORNOS ─────────────────────────────────────────
def pagamento_sucesso(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    pedido.status = 'confirmado'
    pedido.save()
    return render(request, 'pagamento_sucesso.html', {'pedido': pedido})


def pagamento_falha(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    return render(request, 'pagamento_falha.html', {'pedido': pedido})


def pagamento_pendente(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id)
    pedido.status = 'pendente'
    pedido.save()
    return render(request, 'pagamento_pendente.html', {'pedido': pedido})


# ── MERCADO PAGO: WEBHOOK ──────────────────────────────────────────
@csrf_exempt
@require_POST
def webhook_mercadopago(request):
    sdk = mercadopago.SDK(settings.MERCADOPAGO_ACCESS_TOKEN)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"status": "erro"}, status=400)

    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        payment_info = sdk.payment().get(payment_id)
        payment = payment_info["response"]

        pedido_id = payment.get("external_reference")
        status = payment.get("status")

        try:
            pedido = Pedido.objects.get(id=pedido_id)
            if status == "approved":
                pedido.status = "confirmado"
            elif status == "pending":
                pedido.status = "pendente"
            elif status in ["cancelled", "rejected"]:
                pedido.status = "cancelado"
            pedido.save()
        except Pedido.DoesNotExist:
            pass

    return JsonResponse({"status": "ok"})


# ── PÁGINAS ESTÁTICAS ──────────────────────────────────────────────
def pagina_404(request, exception):
    return render(request, '404.html', status=404)

def sobre(request):
    return render(request, 'sobre.html', {'qtd_carrinho': get_carrinho_info(request)})

def contato(request):
    return render(request, 'contato.html', {'qtd_carrinho': get_carrinho_info(request)})

def politica(request):
    return render(request, 'politica.html')