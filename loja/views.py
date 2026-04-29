from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Produto, Carrinho, ItemCarrinho, Pedido, ItemPedido, PerfilCliente, Categoria, calcular_frete_por_estado
import mercadopago
import json
import requests as http_requests
import os
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)



# ── E-MAIL: CONFIRMAÇÃO DE PEDIDO VIA BREVO ───────────────────────
def enviar_email_confirmacao(pedido):
    """Envia e-mail de confirmação para o cliente via Brevo."""
    try:
        itens_html = ''.join([
            f"""<tr>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#6B5E53">{item.nome_produto}</td>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#6B5E53;text-align:center">{item.quantidade}</td>
              <td style="padding:10px 0;border-bottom:1px solid #e8ede3;font-size:14px;color:#8A947C;text-align:right;font-weight:600">R$ {item.preco_unitario}</td>
            </tr>"""
            for item in pedido.itens.all()
        ])

        frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Grátis 🎉"

        html = f"""
        <!DOCTYPE html>
        <html>
        <body style="margin:0;padding:0;background:#F5F2EC;font-family:'Arial',sans-serif">
          <div style="max-width:560px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(107,94,83,0.08)">

            <div style="background:#8A947C;padding:32px 40px;text-align:center">
              <h1 style="color:#fff;font-size:24px;margin:0;letter-spacing:-0.5px">Barrs Store</h1>
              <p style="color:#E8EDE3;font-size:13px;margin:8px 0 0">Acessórios modernos e exclusivos</p>
            </div>

            <div style="padding:40px">
              <div style="text-align:center;margin-bottom:28px">
                <div style="width:64px;height:64px;background:#E8EDE3;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:28px;margin-bottom:16px">✓</div>
                <h2 style="color:#3d2d20;font-size:22px;margin:0 0 8px">Pedido confirmado!</h2>
                <p style="color:#9E9488;font-size:14px;margin:0">Obrigada pela sua compra, <strong style="color:#6B5E53">{pedido.nome}</strong>!</p>
              </div>

              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">PEDIDO #{pedido.id}</p>
                <table style="width:100%;border-collapse:collapse">
                  <tr>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:left;padding-bottom:8px">Produto</th>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:center;padding-bottom:8px">Qtd</th>
                    <th style="font-size:11px;text-transform:uppercase;color:#9E9488;text-align:right;padding-bottom:8px">Valor</th>
                  </tr>
                  {itens_html}
                  <tr>
                    <td colspan="2" style="padding-top:12px;font-size:13px;color:#9E9488">Frete</td>
                    <td style="padding-top:12px;font-size:13px;color:#8A947C;text-align:right;font-weight:600">{frete_texto}</td>
                  </tr>
                  <tr>
                    <td colspan="2" style="padding-top:8px;font-size:15px;font-weight:700;color:#3d2d20">Total</td>
                    <td style="padding-top:8px;font-size:15px;font-weight:700;color:#8A947C;text-align:right">R$ {pedido.total}</td>
                  </tr>
                </table>
              </div>

              <div style="background:#F5F2EC;border-radius:10px;padding:20px;margin-bottom:24px">
                <p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">ENDEREÇO DE ENTREGA</p>
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

        brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
        if not brevo_api_key:
            logger.warning('BREVO_API_KEY nao configurada. E-mail do pedido %s nao foi enviado.', pedido.id)
            return

        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={
                'api-key': brevo_api_key,
                'Content-Type': 'application/json',
            },
            json={
                'sender': {'name': 'Barrs Store', 'email': 'contato.barrsstore@gmail.com'},
                'to': [{'email': pedido.email, 'name': pedido.nome}],
                'subject': f'Pedido #{pedido.id} confirmado - Barrs Store',
                'htmlContent': html,
            },
            timeout=10,
        )
        if resposta.status_code >= 400:
            logger.warning(
                'Brevo recusou o e-mail do pedido %s. Status %s: %s',
                pedido.id,
                resposta.status_code,
                resposta.text[:500],
            )
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail Brevo do pedido %s: %s', pedido.id, exc)


# ── WHATSAPP: NOTIFICAÇÃO DE NOVO PEDIDO ──────────────────────────
def enviar_whatsapp_pedido(pedido):
    """Envia notificação no WhatsApp quando chegar um novo pedido."""
    try:
        itens_texto = ', '.join(
            f"{item.quantidade}x {item.nome_produto}{f' - Tam. {item.tamanho}' if item.tamanho else ''}"
            for item in pedido.itens.all()
        )

        frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Grátis"

        mensagem = (
            f"🛍️ NOVO PEDIDO #{pedido.id}\n\n"
            f"👤 {pedido.nome}\n"
            f"📱 {pedido.telefone}\n"
            f"📧 {pedido.email}\n\n"
            f"📦 Itens: {itens_texto}\n\n"
            f"💰 Subtotal: R$ {pedido.subtotal}\n"
            f"🚚 Frete: {frete_texto}\n"
            f"💎 Total: R$ {pedido.total}\n\n"
            f"💳 Pagamento: {pedido.get_forma_pagamento_display()}\n"
            f"📍 Endereço: {pedido.rua}, {pedido.numero} - {pedido.cidade}/{pedido.estado}"
        )

        http_requests.get(
            'https://api.callmebot.com/whatsapp.php',
            params={
                'phone': '5511913225256',
                'text': mensagem,
                'apikey': '7650859',
            },
            timeout=10,
        )
    except Exception:
        pass  # Nunca quebra o pedido se o WhatsApp falhar


# ── HELPER: dados do carrinho para navbar ──────────────────────────
def get_carrinho_info(request):
    carrinho_id = request.session.get('carrinho_id')
    qtd_carrinho = 0
    if carrinho_id:
        try:
            carrinho = Carrinho.objects.get(id=carrinho_id)
            qtd_carrinho = sum(item.quantidade for item in carrinho.itens.all())
        except Carrinho.DoesNotExist:
            request.session.pop('carrinho_id', None)
    return qtd_carrinho


# ── HOME ───────────────────────────────────────────────────────────
def home(request):
    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')
    categoria_slug = request.GET.get('categoria', '')

    produtos = Produto.objects.all()

    if busca:
        produtos = produtos.filter(
            Q(nome__icontains=busca) | Q(descricao__icontains=busca)
        )

    if categoria_slug:
        produtos = produtos.filter(categoria__slug=categoria_slug)

    if ordem == 'menor':
        produtos = produtos.order_by('preco')
    elif ordem == 'maior':
        produtos = produtos.order_by('-preco')
    elif ordem == 'nome':
        produtos = produtos.order_by('nome')
    else:
        produtos = produtos.order_by('-criado_em')

    categorias = Categoria.objects.all()

    return render(request, 'home.html', {
        'produtos': produtos,
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': Produto.objects.count(),
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
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

    try:
        carrinho = Carrinho.objects.get(id=carrinho_id)
    except Carrinho.DoesNotExist:
        request.session.pop('carrinho_id', None)
        return render(request, 'carrinho.html', {
            'itens': [],
            'total': 0,
            'qtd_carrinho': 0,
        })

    return render(request, 'carrinho.html', {
        'itens': carrinho.itens.all(),
        'total': carrinho.total(),
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── CALCULAR FRETE VIA CEP (AJAX) ─────────────────────────────────
def calcular_frete_ajax(request):
    """Endpoint chamado pelo JS do checkout quando o cliente digita o CEP."""
    from decimal import Decimal
    estado = request.GET.get('estado', '').upper().strip()
    try:
        total = Decimal(request.GET.get('total', '0'))
    except Exception:
        total = Decimal('0')

    frete, minimo = calcular_frete_por_estado(estado, total)
    frete_gratis = frete == Decimal('0')
    falta = max(minimo - total, Decimal('0'))

    return JsonResponse({
        'frete': float(frete),
        'total_com_frete': float(total + frete),
        'frete_gratis': frete_gratis,
        'falta_frete_gratis': float(falta),
        'minimo_gratis': float(minimo),
        'estado': estado,
    })


# ── CALCULAR FRETE VIA MELHOR ENVIO ───────────────────────────────
def calcular_frete_melhor_envio(request):
    """Calcula frete real via API do Melhor Envio pelo CEP."""
    cep_destino = request.GET.get('cep', '').replace('-', '').replace(' ', '')
    
    if len(cep_destino) != 8:
        return JsonResponse({'erro': 'CEP inválido'}, status=400)
    
    token = os.environ.get('MELHOR_ENVIO_TOKEN', '').strip()
    if not token:
        return JsonResponse({'erro': 'Frete indisponível no momento.'}, status=503)
    
    try:
        res = http_requests.post(
            'https://melhorenvio.com.br/api/v2/me/shipment/calculate',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'BarrsStore contato.barrsstore@gmail.com',
            },
            json={
                'from': {'postal_code': '01310100'},  # CEP origem SP
                'to': {'postal_code': cep_destino},
                'package': {
                    'height': 4,
                    'width': 11,
                    'length': 16,
                    'weight': 0.3,
                },
                'options': {
                    'receipt': False,
                    'own_hand': False,
                },
                'services': '1,2',  # 1=PAC, 2=Sedex
            },
            timeout=10,
        )
        
        data = res.json()
        if res.status_code >= 400 or not isinstance(data, list):
            return JsonResponse({'erro': 'Não foi possível calcular o frete agora.'}, status=502)
        opcoes = []
        
        for servico in data:
            if 'error' not in servico and servico.get('price'):
                opcoes.append({
                    'id': servico.get('id'),
                    'nome': servico.get('name', ''),
                    'empresa': servico.get('company', {}).get('name', ''),
                    'preco': float(servico.get('price', 0)),
                    'prazo': servico.get('delivery_time', ''),
                })
        
        opcoes.sort(key=lambda x: x['preco'])
        return JsonResponse({'opcoes': opcoes})
        
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)


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

    quantidade = int(request.POST.get('quantidade', request.GET.get('quantidade', 1)))
    tamanho = request.POST.get('tamanho', request.GET.get('tamanho', ''))

    item, criado = ItemCarrinho.objects.get_or_create(
        carrinho=carrinho,
        produto=produto,
        tamanho=tamanho,
    )

    if criado:
        item.quantidade = quantidade
    else:
        item.quantidade += quantidade
    item.save()

    next_url = request.POST.get('next', request.GET.get('next', 'carrinho'))
    if next_url == 'detalhe':
        from django.urls import reverse
        url = reverse('detalhe_produto', args=[produto_id]) + '?added=1'
        return redirect(url)
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
        estado_pedido = request.POST.get('estado', 'SP')
        subtotal = carrinho.total()
        # Usa frete selecionado no carrinho (Melhor Envio) ou fallback por região.
        frete_selecionado = request.POST.get('frete_valor', '').replace(',', '.').strip()
        if frete_selecionado:
            try:
                frete = Decimal(frete_selecionado)
                if frete < 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                frete, _ = calcular_frete_por_estado(estado_pedido, subtotal)
        else:
            frete, _ = calcular_frete_por_estado(estado_pedido, subtotal)
        total = subtotal + frete

        pedido = Pedido.objects.create(
            cliente=request.user if request.user.is_authenticated else None,
            nome=request.POST['nome'],
            email=request.POST['email'],
            telefone=request.POST.get('telefone', ''),
            cep=request.POST['cep'],
            rua=request.POST['rua'],
            numero=request.POST['numero'],
            complemento=request.POST.get('complemento', ''),
            bairro=request.POST['bairro'],
            cidade=request.POST['cidade'],
            estado=estado_pedido,
            forma_pagamento='pix',
            subtotal=subtotal,
            frete=frete,
            total=total,
        )

        for item in itens:
            ItemPedido.objects.create(
                pedido=pedido,
                produto=item.produto,
                nome_produto=item.produto.nome,
                quantidade=item.quantidade,
                preco_unitario=item.produto.preco,
                tamanho=item.tamanho,
            )

        carrinho.delete()
        del request.session['carrinho_id']

        # Criar conta se solicitado e não estiver logado
        senha = request.POST.get('senha', '').strip()
        if senha and not request.user.is_authenticated:
            email_cadastro = request.POST['email']
            if not User.objects.filter(email=email_cadastro).exists():
                user = User.objects.create_user(
                    username=email_cadastro,
                    email=email_cadastro,
                    password=senha,
                    first_name=request.POST.get('nome', '').split()[0],
                    last_name=' '.join(request.POST.get('nome', '').split()[1:]),
                )
                perfil, _ = PerfilCliente.objects.get_or_create(user=user)
                perfil.telefone = request.POST.get('telefone', '')
                perfil.cep = request.POST.get('cep', '')
                perfil.rua = request.POST.get('rua', '')
                perfil.numero = request.POST.get('numero', '')
                perfil.complemento = request.POST.get('complemento', '')
                perfil.bairro = request.POST.get('bairro', '')
                perfil.cidade = request.POST.get('cidade', '')
                perfil.estado = request.POST.get('estado', '')
                perfil.save()
                pedido.cliente = user
                pedido.save()
                from django.contrib.auth import login as auth_login
                auth_login(request, user)

        # Notificações
        enviar_whatsapp_pedido(pedido)
        enviar_email_confirmacao(pedido)

        return redirect('confirmacao', pedido_id=pedido.id)

    perfil = None
    if request.user.is_authenticated:
        perfil, _ = PerfilCliente.objects.get_or_create(user=request.user)

    return render(request, 'checkout.html', {
        'itens': itens,
        'total': carrinho.total(),
        'qtd_carrinho': get_carrinho_info(request),
        'perfil': perfil,
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

    # Adiciona frete como item separado se houver
    if pedido.frete > 0:
        items.append({
            "title": "Frete",
            "quantity": 1,
            "unit_price": float(pedido.frete),
            "currency_id": "BRL",
        })

    # Limpa telefone — MP só aceita números
    telefone_limpo = "".join(filter(str.isdigit, pedido.telefone or ""))

    payer = {
        "name": pedido.nome,
        "email": pedido.email if pedido.email else "cliente@barrsstore.com.br",
    }
    if len(telefone_limpo) >= 10:
        payer["phone"] = {
            "area_code": telefone_limpo[:2],
            "number": telefone_limpo[2:],
        }

    preference_data = {
        "items": items,
        "payer": payer,
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


# ── CADASTRO ───────────────────────────────────────────────────────
def cadastro(request):
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        nome = request.POST.get('nome', '').strip()
        email = request.POST.get('email', '').strip()
        senha = request.POST.get('senha', '')
        senha2 = request.POST.get('senha2', '')

        if senha != senha2:
            messages.error(request, 'As senhas não coincidem.')
        elif User.objects.filter(email=email).exists():
            messages.error(request, 'Este e-mail já está cadastrado.')
        elif len(senha) < 6:
            messages.error(request, 'A senha deve ter pelo menos 6 caracteres.')
        else:
            partes = nome.split()
            user = User.objects.create_user(
                username=email,
                email=email,
                password=senha,
                first_name=partes[0] if partes else '',
                last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
            )
            PerfilCliente.objects.create(user=user)
            login(request, user)
            messages.success(request, 'Conta criada com sucesso!')
            return redirect('minha_conta')

    return render(request, 'cadastro.html', {'qtd_carrinho': get_carrinho_info(request)})


# ── LOGIN ──────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect('minha_conta')

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        senha = request.POST.get('senha', '')
        user = authenticate(request, username=email, password=senha)
        if user:
            login(request, user)
            next_url = request.GET.get('next', 'minha_conta')
            return redirect(next_url)
        else:
            messages.error(request, 'E-mail ou senha incorretos.')

    return render(request, 'login.html', {'qtd_carrinho': get_carrinho_info(request)})


# ── LOGOUT ─────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('home')


# ── MINHA CONTA ────────────────────────────────────────────────────
@login_required(login_url='/login/')
def minha_conta(request):
    perfil, _ = PerfilCliente.objects.get_or_create(user=request.user)
    pedidos = Pedido.objects.filter(cliente=request.user).order_by('-criado_em')

    if request.method == 'POST':
        request.user.first_name = request.POST.get('primeiro_nome', '').strip()
        request.user.last_name = request.POST.get('ultimo_nome', '').strip()
        request.user.save()

        perfil.telefone = request.POST.get('telefone', '').strip()
        perfil.cep = request.POST.get('cep', '').strip()
        perfil.rua = request.POST.get('rua', '').strip()
        perfil.numero = request.POST.get('numero', '').strip()
        perfil.complemento = request.POST.get('complemento', '').strip()
        perfil.bairro = request.POST.get('bairro', '').strip()
        perfil.cidade = request.POST.get('cidade', '').strip()
        perfil.estado = request.POST.get('estado', '').strip()
        perfil.save()

        messages.success(request, 'Dados atualizados com sucesso!')
        return redirect('minha_conta')

    return render(request, 'minha_conta.html', {
        'perfil': perfil,
        'pedidos': pedidos,
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── DETALHE DO PEDIDO (cliente) ────────────────────────────────────
@login_required(login_url='/login/')
def detalhe_pedido(request, pedido_id):
    pedido = get_object_or_404(Pedido, id=pedido_id, cliente=request.user)
    return render(request, 'detalhe_pedido.html', {
        'pedido': pedido,
        'qtd_carrinho': get_carrinho_info(request),
    })


# ── PÁGINAS ESTÁTICAS ──────────────────────────────────────────────
def pagina_404(request, exception):
    return render(request, '404.html', status=404)

def entrega(request):
    return render(request, 'entrega.html', {'qtd_carrinho': get_carrinho_info(request)})

def sobre(request):
    return render(request, 'sobre.html', {'qtd_carrinho': get_carrinho_info(request)})

def contato(request):
    return render(request, 'contato.html', {'qtd_carrinho': get_carrinho_info(request)})

def politica(request):
    return render(request, 'politica.html')