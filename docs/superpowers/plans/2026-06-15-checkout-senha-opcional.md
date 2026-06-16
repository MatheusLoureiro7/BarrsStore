# Checkout Senha Opcional — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar o campo de senha no checkout opcional — se não preenchido, o backend gera senha aleatória, cria a conta e envia a senha por email imediatamente.

**Architecture:** Três mudanças encadeadas: (1) nova função de email em `emails.py`; (2) `_resolver_cliente()` em `cart.py` passa a retornar tupla `(user, senha_gerada|None)` e trata os 5 casos de senha/sem-senha; (3) template remove `required` do campo.

**Tech Stack:** Django 4.x, Python `secrets` (stdlib), Brevo (email), testes com `unittest.mock.patch`

---

## Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `loja/views/emails.py` | Nova função `enviar_email_conta_criada(pedido, senha)` |
| `loja/views/cart.py` | `_resolver_cliente` retorna tupla; `checkout()` desempacota e dispara email |
| `loja/templates/checkout.html` | Remove `required`/`minlength`, atualiza placeholder e hint |
| `loja/tests.py` | Testes novos para os 4 cenários de senha opcional |

---

## Task 1: Função `enviar_email_conta_criada` em `emails.py`

**Files:**
- Modify: `loja/views/emails.py`
- Test: `loja/tests.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicionar ao final da classe `CheckoutTests` (linha ~486 em `loja/tests.py`). Primeiro adicionar os imports necessários no topo do arquivo (verificar se já existem):

```python
from unittest.mock import patch, MagicMock
```

Adicionar nova classe de teste após `CheckoutTests`:

```python
class EnviarEmailContaCriadaTests(TestCase):
    def _make_pedido(self):
        from loja.models import Produto, Carrinho, ItemCarrinho, Pedido
        produto = Produto.objects.create(nome='Anel Teste', preco=100, estoque=5)
        carrinho = Carrinho.objects.create()
        ItemCarrinho.objects.create(carrinho=carrinho, produto=produto, quantidade=1)
        from django.contrib.auth.models import User
        user = User.objects.create_user(username='t@test.com', email='t@test.com', password='x')
        return Pedido.objects.create(
            cliente=user,
            nome='Ana Teste',
            email='t@test.com',
            telefone='11999999999',
            cpf='12345678901',
            cep='01001000',
            rua='Rua Teste',
            numero='1',
            bairro='Centro',
            cidade='São Paulo',
            estado='SP',
            forma_pagamento='pendente',
            subtotal=100,
            desconto=0,
            frete=10,
            total=110,
        )

    @patch('loja.views.emails.enviar_brevo_payload')
    def test_envia_email_com_senha_no_corpo(self, mock_brevo):
        mock_brevo.return_value = (True, '', MagicMock())
        from loja.views.emails import enviar_email_conta_criada
        pedido = self._make_pedido()
        resultado = enviar_email_conta_criada(pedido, 'SenhaXYZ123')
        self.assertTrue(resultado)
        mock_brevo.assert_called_once()
        payload = mock_brevo.call_args[0][0]
        self.assertIn('SenhaXYZ123', payload['htmlContent'])
        self.assertIn(pedido.email, payload['to'][0]['email'])

    @patch('loja.views.emails.enviar_brevo_payload')
    def test_enfileira_quando_brevo_falha(self, mock_brevo):
        mock_brevo.return_value = (False, 'timeout', None)
        from loja.views.emails import enviar_email_conta_criada
        from loja.models import EmailPendente
        pedido = self._make_pedido()
        resultado = enviar_email_conta_criada(pedido, 'SenhaXYZ123')
        self.assertFalse(resultado)
        self.assertTrue(EmailPendente.objects.filter(destinatario_email=pedido.email).exists())
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py test loja.tests.EnviarEmailContaCriadaTests -v 2
```

Esperado: `ImportError: cannot import name 'enviar_email_conta_criada'`

- [ ] **Step 3: Implementar `enviar_email_conta_criada` em `loja/views/emails.py`**

Adicionar após `enviar_email_confirmacao` (aproximadamente após linha 370):

```python
def enviar_email_conta_criada(pedido, senha):
    """Email imediato quando conta é criada automaticamente no checkout sem senha."""
    try:
        link_minha_conta = site_url(reverse('minha_conta'))
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        primeiro_nome = pedido.nome.split()[0]

        card_senha = (
            '<div style="background:#FAFAF7;border:2px solid #C8A96A;border-radius:14px;'
            'padding:18px 24px;margin:20px 0;text-align:center">'
            '<p style="margin:0 0 6px;color:#8A8178;font-size:10px;font-weight:700;'
            'letter-spacing:0.14em;text-transform:uppercase">Sua conta foi criada automaticamente</p>'
            f'<p style="margin:0 0 4px;color:#4A4038;font-size:22px;font-weight:800;'
            f'letter-spacing:0.08em;font-family:monospace">{senha}</p>'
            '<p style="margin:6px 0 0;color:#8A8178;font-size:12px">'
            'Voc&ecirc; pode alter&aacute;-la depois em Minha Conta</p>'
            '</div>'
        )
        corpo = (
            _paragrafo(f'Ol&aacute;, <strong style="color:#4A4038">{primeiro_nome}</strong>! '
                       'Seu pedido foi criado com sucesso.')
            + card_senha
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:20px 0">'
            f'{_btn("Finalizar pagamento", link_pagamento, "#C8A96A")}'
            f'&nbsp;&nbsp;'
            f'{_btn("Minha conta", link_minha_conta)}'
            f'</div>'
            + _paragrafo(
                '<span style="color:#8A8178;font-size:13px">'
                'Guarde sua senha em lugar seguro. D&uacute;vidas? Estamos no WhatsApp.'
                '</span>'
            )
        )
        html = _email_wrapper(
            'Sua conta foi criada &#10024;',
            corpo,
            f'Pedido #{pedido.id} criado &middot; sua senha de acesso est&aacute; aqui',
        )
        payload = _brevo_payload(
            pedido.email,
            pedido.nome,
            f'Sua conta na Barrs Store foi criada — pedido #{pedido.id}',
            html,
        )
        ok, erro, resposta = enviar_brevo_payload(payload)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='conta_criada')
            logger.warning('[BREVO] Email conta_criada pedido %s enfileirado. erro=%s', pedido.id, erro)
            return False
        logger.info('[BREVO] Email conta_criada pedido %s enviado.', pedido.id)
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar email conta_criada pedido %s: %s', pedido.id, exc)
        return False
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py test loja.tests.EnviarEmailContaCriadaTests -v 2
```

Esperado: `OK (2 tests)`

---

## Task 2: Atualizar `_resolver_cliente` em `cart.py`

**Files:**
- Modify: `loja/views/cart.py`
- Test: `loja/tests.py`

- [ ] **Step 1: Escrever os testes que falham**

Adicionar classe após `EnviarEmailContaCriadaTests` em `loja/tests.py`:

```python
class CheckoutSenhaOpcionalTests(TestCase):
    def _setup_carrinho(self, client):
        produto = Produto.objects.create(nome='Anel Teste', preco=100, estoque=5)
        carrinho = Carrinho.objects.create()
        ItemCarrinho.objects.create(carrinho=carrinho, produto=produto, quantidade=1)
        session = client.session
        session['carrinho_id'] = carrinho.id
        session.save()
        return carrinho

    def _dados_base(self, email='novo@example.com', senha=''):
        return {
            'nome': 'Cliente Novo',
            'email': email,
            'telefone': '11999999999',
            'cpf': '529.982.247-25',  # CPF válido
            'cep': '01001000',
            'rua': 'Rua Teste',
            'numero': '10',
            'bairro': 'Centro',
            'cidade': 'São Paulo',
            'estado': 'SP',
            'frete_valor': '15.00',
            'senha': senha,
        }

    @patch('loja.views.cart.enviar_email_conta_criada')
    @patch('loja.views.cart.enviar_whatsapp_pedido')
    def test_email_novo_sem_senha_cria_usuario_com_senha_gerada(self, mock_wa, mock_email_conta):
        """Novo email sem senha: cria user, gera senha, chama enviar_email_conta_criada."""
        c = Client()
        self._setup_carrinho(c)
        c.post('/finalizar/', self._dados_base(email='novo@example.com', senha=''))
        user = User.objects.filter(email='novo@example.com').first()
        self.assertIsNotNone(user, 'Usuário deve ter sido criado')
        self.assertTrue(mock_email_conta.called, 'Email de conta criada deve ser disparado')
        pedido_arg, senha_arg = mock_email_conta.call_args[0]
        self.assertIsNotNone(senha_arg)
        self.assertGreater(len(senha_arg), 0)

    @patch('loja.views.cart.enviar_email_conta_criada')
    @patch('loja.views.cart.enviar_whatsapp_pedido')
    def test_email_existente_sem_senha_usa_usuario_sem_login(self, mock_wa, mock_email_conta):
        """Email existente sem senha: usa o user existente, não dispara email de conta criada."""
        user_existente = User.objects.create_user(
            username='existente@example.com',
            email='existente@example.com',
            password='SenhaAntiga123',
        )
        c = Client()
        self._setup_carrinho(c)
        c.post('/finalizar/', self._dados_base(email='existente@example.com', senha=''))
        from loja.models import Pedido
        pedido = Pedido.objects.filter(email='existente@example.com').first()
        self.assertIsNotNone(pedido, 'Pedido deve ter sido criado')
        self.assertEqual(pedido.cliente, user_existente)
        self.assertFalse(mock_email_conta.called, 'Email de conta criada NÃO deve ser disparado')

    @patch('loja.views.cart.enviar_email_conta_criada')
    @patch('loja.views.cart.enviar_whatsapp_pedido')
    def test_com_senha_valida_nao_dispara_email_conta_criada(self, mock_wa, mock_email_conta):
        """Com senha fornecida: fluxo normal, sem email de conta criada."""
        c = Client()
        self._setup_carrinho(c)
        c.post('/finalizar/', self._dados_base(email='comsenha@example.com', senha='SenhaForte123!'))
        self.assertFalse(mock_email_conta.called)
        user = User.objects.filter(email='comsenha@example.com').first()
        self.assertIsNotNone(user)
```

- [ ] **Step 2: Rodar para confirmar que falham**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py test loja.tests.CheckoutSenhaOpcionalTests -v 2
```

Esperado: os 3 testes falham (comportamento atual exige senha).

- [ ] **Step 3: Atualizar `_resolver_cliente` em `loja/views/cart.py`**

Adicionar `import secrets` no topo do arquivo (logo após os imports existentes de `django.core.exceptions`):

```python
import secrets
```

Substituir a função `_resolver_cliente` inteira (linhas 199–249):

```python
def _gerar_senha():
    return secrets.token_urlsafe(9)


def _resolver_cliente(request, dados):
    """Resolve o usuário do pedido. Retorna (user, senha_gerada|None).

    senha_gerada é não-nula apenas quando uma nova conta foi criada sem senha
    fornecida pelo cliente — sinaliza que o email de boas-vindas deve ser enviado.
    """
    if request.user.is_authenticated:
        return request.user, None

    email_pedido = dados['email']
    senha = request.POST.get('senha', '').strip()
    senha_gerada = None

    usuario_existente = User.objects.filter(email__iexact=email_pedido).first()

    if usuario_existente:
        if senha:
            user = authenticate(request, username=usuario_existente.username, password=senha)
            if not user:
                messages.error(request, 'Nao foi possivel validar suas credenciais. Confira os dados e tente novamente.')
                return None, None
            login(request, user)
        else:
            # Sem senha: vincula o pedido ao usuário existente sem autenticar a sessão.
            user = usuario_existente
    else:
        if senha:
            partes = dados['nome'].split()
            user_preview = User(
                username=email_pedido,
                email=email_pedido,
                first_name=partes[0] if partes else '',
                last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
            )
            try:
                validate_password(senha, user_preview)
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
                return None, None
            user = User.objects.create_user(
                username=email_pedido,
                email=email_pedido,
                password=senha,
                first_name=partes[0] if partes else '',
                last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
            )
            login(request, user)
        else:
            partes = dados['nome'].split()
            senha_gerada = _gerar_senha()
            user = User.objects.create_user(
                username=email_pedido,
                email=email_pedido,
                password=senha_gerada,
                first_name=partes[0] if partes else '',
                last_name=' '.join(partes[1:]) if len(partes) > 1 else '',
            )
            login(request, user)

    perfil, _ = PerfilCliente.objects.get_or_create(user=user)
    perfil.telefone = dados['telefone']
    perfil.cep = dados['cep']
    perfil.rua = dados['rua']
    perfil.numero = dados['numero']
    perfil.complemento = dados['complemento']
    perfil.bairro = dados['bairro']
    perfil.cidade = dados['cidade']
    perfil.estado = dados['estado']
    perfil.save()
    return user, senha_gerada
```

- [ ] **Step 4: Atualizar o import de emails e o chamador em `checkout()` em `cart.py`**

Atualizar o import existente na linha 35:

```python
from .emails import enviar_whatsapp_pedido, enviar_email_conta_criada
```

Na função `checkout()`, substituir as linhas que chamam `_resolver_cliente` e `_criar_pedido_com_itens`:

```python
        cliente, senha_gerada = _resolver_cliente(request, dados)
        if cliente is None:
            return render_checkout()

        pedido = _criar_pedido_com_itens(carrinho, itens, dados, cliente, request.session.get('utm') or {})
        if dados.get('lead_cupom'):
            dados['lead_cupom'].usado_em_pedido = pedido
            dados['lead_cupom'].save(update_fields=['usado_em_pedido'])
        request.session.pop('carrinho_id', None)
        if senha_gerada:
            enviar_email_conta_criada(pedido, senha_gerada)
        _notificar_novo_pedido(pedido)
        return redirect('confirmacao', pedido_id=pedido.id, token=pedido.access_token)
```

- [ ] **Step 5: Rodar os testes novos**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py test loja.tests.CheckoutSenhaOpcionalTests -v 2
```

Esperado: `OK (3 tests)`

---

## Task 3: Atualizar o template `checkout.html`

**Files:**
- Modify: `loja/templates/checkout.html` (linhas 97–99)

- [ ] **Step 1: Substituir o bloco do campo senha**

Localizar o bloco atual (dentro de `{% if not user.is_authenticated %}`):

```html
          <input type="password" name="senha" placeholder="Senha (mínimo 8 caracteres)" minlength="8" required>
          <div class="account-callout__hint">Obrigatória para finalizar e acompanhar seu pedido</div>
```

Substituir por:

```html
          <input type="password" name="senha" placeholder="Deixe em branco para gerar automaticamente">
          <div class="account-callout__hint">Se não preencher, criamos uma senha automaticamente e enviamos por e-mail</div>
```

- [ ] **Step 2: Rodar a suite completa para garantir nenhuma regressão**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py test loja -v 2
```

Esperado: todos os testes passando (incluindo o `test_checkout_bloqueia_cpf_invalido` existente).

---

## Task 4: Verificação manual

- [ ] **Step 1: Subir o servidor local**

```bash
cd /Users/bibico/Documents/projetos/BarrsStore && python manage.py runserver
```

- [ ] **Step 2: Acessar o checkout e verificar o campo de senha**

Abrir `http://127.0.0.1:8000/finalizar/` (com item no carrinho).
Confirmar que o campo senha existe, não tem `required`, e mostra o placeholder correto.

- [ ] **Step 3: Testar checkout sem senha com email novo**

Preencher todos os campos exceto senha com um email inexistente no banco.
Confirmar que o checkout avança para a página de confirmação.
Verificar no shell Django que o usuário foi criado:

```bash
python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(email='email_testado@example.com').exists())"
```

- [ ] **Step 4: Confirmar email de boas-vindas nos logs**

Verificar no terminal do servidor a linha `[BREVO] Email conta_criada pedido X enviado.` ou, se sem chave Brevo, `enfileirado`.
