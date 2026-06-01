# Análise Completa — BarrsStore Django

> Gerado em: 2026-06-01

---

## 1. SEGURANÇA

---

### [SEG-01] `.env` commitado com credenciais reais
**Arquivo:** `.env` (raiz do projeto)
**Prioridade: ALTA**

O arquivo `.env` está tracked pelo git. Contém credenciais ativas:
- `CLOUDINARY_URL` com API key/secret
- `MELHOR_ENVIO_TOKEN` (JWT)
- `META_ACCESS_TOKEN`
- `MP_WEBHOOK_SECRET`

**Correção:**
```bash
# 1. Remover do tracking
echo ".env" >> .gitignore
git rm --cached .env
git commit -m "Remove .env do tracking"

# 2. Criar .env.example sem valores reais
# 3. Rotacionar TODOS os tokens expostos no histórico git
```

---

### [SEG-02] Open redirect no login
**Arquivo:** `loja/views.py:2665`
**Prioridade: ALTA**

```python
# ATUAL — vulnerável
next_url = request.GET.get('next', 'minha_conta')
return redirect(next_url)
```

O parâmetro `next` é passado direto para `redirect()` sem validação. `url_has_allowed_host_and_scheme` já é importado (linha 5) e usado na linha 1894 (add_to_cart), mas foi omitido no login_view.

**Correção:**
```python
from django.utils.http import url_has_allowed_host_and_scheme

next_url = request.GET.get('next', '')
allowed = {request.get_host()}
if next_url and url_has_allowed_host_and_scheme(
    next_url, allowed_hosts=allowed, require_https=not settings.DEBUG
):
    return redirect(next_url)
return redirect('minha_conta')
```

---

### [SEG-03] Webhook do Mercado Pago processa requests com assinatura inválida
**Arquivo:** `loja/views.py:2565-2570`
**Prioridade: ALTA**

```python
assinatura_ok, motivo_assinatura = validar_assinatura_mercadopago(request, data)
if not assinatura_ok:
    logger.warning('[MP] Webhook com assinatura nao validada: %s', motivo_assinatura)
    if getattr(settings, 'MERCADOPAGO_WEBHOOK_STRICT', False):  # False por padrão!
        return JsonResponse({"status": "forbidden"}, status=403)
# continua processando mesmo com assinatura inválida
```

`MERCADOPAGO_WEBHOOK_STRICT` é `False` por padrão. Webhooks com assinatura inválida são processados em produção, permitindo confirmações de pagamento forjadas.

**Correção em `settings.py`:**
```python
MERCADOPAGO_WEBHOOK_STRICT = True if not DEBUG else (
    os.environ.get('MP_WEBHOOK_STRICT', 'False') == 'True'
)
```

---

### [SEG-04] `CACHES` não configurado — webhook dedup falha após restart
**Arquivo:** `barrs_store/settings.py`
**Prioridade: ALTA**

Nenhuma configuração `CACHES` existe. Django usa `LocMemCache` (memória in-process) por padrão. O webhook usa `cache.add(f'mp:wh:{request_id_mp}', '1', 24*60*60)` para deduplicação — essa lógica falha após qualquer restart do container Railway, permitindo reprocessamento do mesmo webhook.

**Correção:**
```python
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    } if DEBUG else {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', ''),
    }
}
```

> Adicionar Redis no Railway (free tier disponível).

---

## 2. PERFORMANCE

---

### [PERF-01] `ItemPedido.objects.create` em loop — N inserts por pedido
**Arquivo:** `loja/views.py:2205-2212`
**Prioridade: ALTA**

```python
# ATUAL — 1 INSERT por item
for item in itens:
    ItemPedido.objects.create(
        pedido=pedido,
        produto=item.produto,
        nome_produto=item.produto.nome,
        quantidade=item.quantidade,
        preco_unitario=item.produto.preco,
        tamanho=item.tamanho,
    )
```

**Correção:**
```python
ItemPedido.objects.bulk_create([
    ItemPedido(
        pedido=pedido,
        produto=item.produto,
        nome_produto=item.produto.nome,
        quantidade=item.quantidade,
        preco_unitario=item.produto.preco,
        tamanho=item.tamanho,
    )
    for item in itens
])
```

---

### [PERF-02] N+1 em função de email — `pedido.itens.all()` sem `select_related`
**Arquivo:** `loja/views.py:933`
**Prioridade: ALTA**

```python
# ATUAL — 1 query por item
for item in pedido.itens.all()
```

O `select_related` já é usado consistentemente no resto do código (linhas 452, 733, 1212, 2013, 2085). Esta linha escapou.

**Correção:**
```python
for item in pedido.itens.select_related('produto').all()
```

---

### [PERF-03] N+1 em linha 2268 — `itens.all()` sem `select_related`
**Arquivo:** `loja/views.py:2268`
**Prioridade: MÉDIA**

Mesmo padrão do PERF-02, em outra função de resumo/email.

**Correção:**
```python
for item in pedido.itens.select_related('produto').all()
```

---

### [PERF-04] `Produto` sem índice composto para listagem
**Arquivo:** `loja/models.py:76-78`
**Prioridade: MÉDIA**

A home filtra `Produto.objects.filter(visivel=True).order_by('-criado_em')` sem índice composto de suporte. O model não tem `class Meta` com `indexes`.

**Correção:**
```python
class Meta:
    ordering = ['-criado_em']
    verbose_name = 'Produto'
    verbose_name_plural = 'Produtos'
    indexes = [
        models.Index(fields=['visivel', '-criado_em']),
        models.Index(fields=['visivel', 'destaque']),
    ]
```

> Gerar migration após a mudança.

---

### [PERF-05] `EmailPendente` sem índice em `(status, criado_em)`
**Arquivo:** `loja/models.py:489-515`
**Prioridade: MÉDIA**

O processamento da fila de emails filtra por `status='pendente'` e ordena por `criado_em`. Nenhum índice composto existe.

**Correção:**
```python
class Meta:
    ordering = ['criado_em']
    indexes = [
        models.Index(fields=['status', 'criado_em']),
    ]
```

---

## 3. CÓDIGO

---

### [COD-01] `views.py` monolítico — 2547 linhas, 97 funções
**Arquivo:** `loja/views.py`
**Prioridade: ALTA**

O arquivo concentra: helpers de email (~600 linhas), integração Melhor Envio (~100 linhas), lógica de pagamento (~300 linhas), autenticação, dashboard, e todas as views de produto/carrinho/checkout.

**Estrutura sugerida:**
```
loja/
  views/
    __init__.py    # re-exporta tudo para manter urls.py funcionando
    store.py       # home, detalhe, busca
    cart.py        # carrinho, checkout
    payment.py     # pagamento, webhook MP, sucesso
    account.py     # login, cadastro, minha conta
    shipping.py    # integração Melhor Envio
    emails.py      # todas as funções de email
    dashboard.py   # admin dashboard
```

---

### [COD-02] `checkout()` com ~230 linhas e múltiplas responsabilidades
**Arquivo:** `loja/views.py:2005-2236`
**Prioridade: ALTA**

A função valida form, cria/atualiza usuário, verifica estoque, cria pedido, baixa estoque, calcula frete, cria envio Melhor Envio, envia email e redireciona.

**Correção — extrair helpers privados:**
```python
def _validar_dados_checkout(request) -> dict | None: ...
def _resolver_cliente(request, dados) -> User: ...
def _criar_pedido_com_itens(carrinho, dados, cliente) -> Pedido: ...
def _processar_envio_melhor_envio(pedido) -> None: ...

def checkout(request):
    dados = _validar_dados_checkout(request)
    cliente = _resolver_cliente(request, dados)
    pedido = _criar_pedido_com_itens(carrinho, dados, cliente)
    _processar_envio_melhor_envio(pedido)
    return redirect(...)
```

---

### [COD-03] 5 funções `enviar_email_poscompra_N` quase idênticas
**Arquivo:** `loja/views.py:1088-1205`
**Prioridade: MÉDIA**

`enviar_email_poscompra_1` até `enviar_email_poscompra_5` têm a mesma estrutura — só variam assunto, corpo e flag no model.

**Correção:**
```python
_POSCOMPRA_CONFIG = {
    1: {'flag': 'email_poscompra_1_enviado', 'assunto': '...', 'titulo': '...'},
    2: {'flag': 'email_poscompra_2_enviado', 'assunto': '...', 'titulo': '...'},
    # ...
}

def enviar_email_poscompra(pedido, etapa: int) -> bool:
    cfg = _POSCOMPRA_CONFIG[etapa]
    if getattr(pedido, cfg['flag']):
        return False
    # monta e envia email
    setattr(pedido, cfg['flag'], True)
    pedido.save(update_fields=[cfg['flag']])
    return True
```

---

### [COD-04] Lógica de frete dividida entre `models.py` e `views.py`
**Arquivo:** `loja/models.py:25` e `loja/views.py:720`
**Prioridade: MÉDIA**

`calcular_frete_por_estado()` está em `models.py` como função livre, mas a integração com Melhor Envio está na view. Lógica de domínio espalhada.

**Correção:** Criar `loja/shipping.py` e consolidar toda a lógica de frete ali.

---

### [COD-05] `Pedido.observacoes` — `TextField` com `max_length`
**Arquivo:** `loja/models.py:395`
**Prioridade: BAIXA**

```python
observacoes = models.TextField(blank=True, default='', max_length=500, ...)
```

`max_length` em `TextField` não é validado pelo PostgreSQL. A validação ocorre apenas em formulários Django. Use `CharField(max_length=500)` se quiser enforcement real, ou remova o `max_length` do `TextField`.

---

## 4. TEMPLATES

---

### [TPL-01] ~418 linhas de JavaScript inline em `confirmacao.html`
**Arquivo:** `loja/templates/confirmacao.html`
**Prioridade: ALTA**

Todo o polling de status PIX, inicialização do Brick do Mercado Pago e tratamento de estados (loading/success/error) está inline no template. Impossível de cachear, testar ou reutilizar.

**Correção:** Extrair para `static/loja/js/confirmacao.js` e carregar com:
```html
<script src="{% static 'loja/js/confirmacao.js' %}" nonce="{{ csp_nonce }}" defer></script>
```

---

### [TPL-02] URLs hardcoded em vez de `{% url %}`
**Arquivo:** `sobre.html`, `contato.html`, `garantia.html`, `politica.html`
**Prioridade: MÉDIA**

```html
<!-- ATUAL -->
<a href="/">Início</a>
<a href="/#produtos">Coleção</a>
```

**Correção:**
```html
<a href="{% url 'home' %}">Início</a>
<a href="{% url 'home' %}#produtos">Coleção</a>
```

---

### [TPL-03] Imagens below-fold sem `loading="lazy"`
**Arquivo:** `sobre.html:153`, `contato.html`, `entrega.html`
**Prioridade: MÉDIA**

Imagens abaixo do fold carregam imediatamente, competindo com o LCP.

**Correção:**
```html
<img src="..." alt="..." loading="lazy" decoding="async">
```

> Não aplicar nas imagens do hero (já têm `loading="eager"` e `fetchpriority="high"`).

---

### [TPL-04] Inline styles em SVGs em vez de classes
**Arquivo:** Múltiplos templates
**Prioridade: BAIXA**

```html
<!-- ATUAL -->
<svg style="width:14px;height:14px" ...>
```

**Correção:**
```html
<svg class="icon icon--sm" ...>
```

---

## 5. MODELS

---

### [MOD-01] `ItemCarrinho` sem `unique_together` — duplicação silenciosa
**Arquivo:** `loja/models.py:331-340`
**Prioridade: ALTA**

Nenhuma constraint impede dois registros `(carrinho, produto, tamanho)` idênticos. Em caso de race condition no add_to_cart, o carrinho acumula itens duplicados em vez de incrementar quantidade.

**Correção:**
```python
class Meta:
    unique_together = [('carrinho', 'produto', 'tamanho')]
    verbose_name = 'Item do carrinho'
    verbose_name_plural = 'Itens do carrinho'
```

---

### [MOD-02] `Produto` sem `class Meta` / sem índices de listagem
**Arquivo:** `loja/models.py:56-88`
**Prioridade: MÉDIA**

Produto é o model mais acessado. `criado_em` não tem `db_index`, `visivel` não tem índice. Queries da home e da busca não têm índice composto de suporte.

> Correção detalhada em PERF-04.

---

### [MOD-03] `Pedido.forma_pagamento` sem `db_index`
**Arquivo:** `loja/models.py:369`
**Prioridade: BAIXA**

Usado em filtros do admin, mas sem índice.

**Correção:**
```python
forma_pagamento = models.CharField(max_length=20, choices=PAGAMENTO_CHOICES, db_index=True)
```

---

## 6. CONFIGURAÇÕES

---

### [CFG-01] `EMAIL_BACKEND` não configurado
**Arquivo:** `barrs_store/settings.py`
**Prioridade: ALTA**

Nenhuma configuração de email existe. Django usa o backend SMTP por padrão e vai falhar silenciosamente se `EMAIL_HOST` não estiver configurado.

**Correção:**
```python
EMAIL_BACKEND = (
    'django.core.mail.backends.console.EmailBackend' if DEBUG
    else 'django.core.mail.backends.smtp.EmailBackend'
)
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = 'Barrs Store <noreply@barrsstore.com.br>'
```

---

### [CFG-02] Gunicorn sem workers configurados
**Arquivo:** `railway.json:8`
**Prioridade: BAIXA**

Sem `--workers`, roda 1 worker síncrono. Para tráfego concorrente mínimo, adicionar workers após configurar Redis (CFG-02 + SEG-04).

**Correção (após Redis):**
```json
"startCommand": "python manage.py migrate --noinput && gunicorn barrs_store.wsgi --workers 2 --bind 0.0.0.0:$PORT --log-file -"
```

---

## Tabela Resumo

| # | ID | Área | Problema | Arquivo | Linha | Prioridade | Status |
|---|----|------|----------|---------|-------|------------|--------|
| 1 | SEG-01 | Segurança | `.env` com credenciais reais commitado | `.env` | — | **ALTA** | ✅ Feito |
| 2 | SEG-02 | Segurança | Open redirect no login (`next` sem validação) | `views.py` | 2665 | **ALTA** | ✅ Feito |
| 3 | SEG-03 | Segurança | Webhook MP processa requests com assinatura inválida | `views.py` | 2568 | **ALTA** | ✅ Feito |
| 4 | SEG-04 | Segurança | `CACHES` não configurado — dedup de webhook falha após restart | `settings.py` | — | **ALTA** | ✅ Feito |
| 5 | CFG-01 | Config | `EMAIL_BACKEND` não configurado | `settings.py` | — | **ALTA** | ✅ Feito |
| 6 | PERF-01 | Performance | `ItemPedido.objects.create` em loop (sem `bulk_create`) | `views.py` | 2205 | **ALTA** | ✅ Feito |
| 7 | PERF-02 | Performance | N+1 em email — `itens.all()` sem `select_related` | `views.py` | 933 | **ALTA** | ✅ Feito |
| 8 | MOD-01 | Models | `ItemCarrinho` sem `unique_together` | `models.py` | 331 | **ALTA** | ✅ Feito |
| 9 | COD-01 | Código | `views.py` monolítico — 2700+ linhas, 97 funções | `views.py` | — | **ALTA** | ✅ Feito |
| 10 | COD-02 | Código | `checkout()` com ~230 linhas, múltiplas responsabilidades | `views.py` | 2005 | **ALTA** | ✅ Feito |
| 11 | TPL-01 | Templates | ~418 linhas de JS inline em `confirmacao.html` | `confirmacao.html` | — | **ALTA** | ✅ Feito |
| 12 | PERF-03 | Performance | N+1 em linha 2268 — `itens.all()` sem `select_related` | `views.py` | 2268 | **MÉDIA** | ✅ Feito |
| 13 | PERF-04 | Performance | `Produto` sem índice composto `(visivel, criado_em)` | `models.py` | 76 | **MÉDIA** | ✅ Feito |
| 14 | PERF-05 | Performance | `EmailPendente` sem índice em `(status, criado_em)` | `models.py` | 508 | **MÉDIA** | ✅ Feito |
| 15 | COD-03 | Código | 5 funções `enviar_email_poscompra_N` quase idênticas | `views.py` | 1088 | **MÉDIA** | ✅ Feito |
| 16 | COD-04 | Código | Lógica de frete dividida entre `models.py` e `views.py` | `models.py` / `views.py` | 25 / 720 | **MÉDIA** | ✅ Feito |
| 17 | MOD-02 | Models | `Produto` sem `class Meta` / sem índices | `models.py` | 56 | **MÉDIA** | ✅ Feito (PERF-04) |
| 18 | TPL-02 | Templates | URLs hardcoded em vez de `{% url %}` | Vários | — | **MÉDIA** | ✅ Feito |
| 19 | TPL-03 | Templates | Imagens below-fold sem `loading="lazy"` | `sobre.html`, etc. | 153+ | **MÉDIA** | ✅ Feito |
| 20 | COD-05 | Código | `TextField` com `max_length` (não enforçado no DB) | `models.py` | 395 | **BAIXA** | ⏳ Backlog |
| 21 | MOD-03 | Models | `Pedido.forma_pagamento` sem `db_index` | `models.py` | 369 | **BAIXA** | ⏳ Backlog |
| 22 | CFG-02 | Config | Gunicorn sem workers configurados | `railway.json` | 8 | **BAIXA** | ⏳ Backlog |
| 23 | TPL-04 | Templates | Inline styles em SVGs em vez de classes CSS | Vários | — | **BAIXA** | ⏳ Backlog |

---

## Histórico de sprints

### Imediato — concluído
- ✅ **SEG-01** — `.env` removido do tracking, adicionado ao `.gitignore`
- ✅ **SEG-03** — `MERCADOPAGO_WEBHOOK_STRICT=True` em produção

### Sprint 1 — concluída
- ✅ **SEG-02** — open redirect no login corrigido com `url_has_allowed_host_and_scheme`
- ✅ **SEG-04 + CFG-01** — Redis como CACHES backend + `EMAIL_BACKEND` configurado
- ✅ **PERF-01** — `bulk_create` substituindo loop de `ItemPedido.objects.create`
- ✅ **PERF-02 + PERF-03** — `select_related('produto')` adicionado nas duas queries N+1
- ✅ **MOD-01** — `unique_together = [('carrinho', 'produto', 'tamanho')]` em `ItemCarrinho`

### Sprint 2 — concluída
- ✅ **PERF-04** — `class Meta` com indexes `(visivel, -criado_em)` e `(visivel, destaque)` em `Produto`
- ✅ **PERF-05** — index `(status, criado_em)` em `EmailPendente`
- ✅ **COD-03** — helper `_enviar_poscompra()` extrai boilerplate das 5 funções poscompra
- ✅ **TPL-01** — JS extraído para `static/loja/js/confirmacao.js`; valores Django via `window.BARRS_PAYMENT_CONFIG`

### Sprint 3 — concluída
- ✅ **COD-01** — `views.py` quebrado em pacote `views/` com 8 módulos (`utils.py`, `store.py`, `cart.py`, `payment.py`, `account.py`, `shipping.py`, `emails.py`, `dashboard.py`) + `__init__.py` re-exportando tudo
- ✅ **COD-02** — `checkout()` decomposto em helpers privados (`_validar_form_checkout`, `_resolver_cliente`, `_criar_pedido_com_itens`, `_notificar_novo_pedido`)

### Sprint 4 — concluída
- ✅ **COD-04** — `calcular_frete_por_estado` + constantes movidos para `loja/shipping.py`; re-exportados de `models.py` (compat com tests) e de `views/shipping.py` (API unificada de frete)
- ✅ **TPL-02** — URLs hardcoded substituídas por `{% url %}` em `sobre.html`, `contato.html`, `garantia.html`, `politica.html`, `entrega.html`
- ✅ **TPL-03** — Imagem below-fold em `sobre.html` já tinha `loading="lazy"`; demais templates (`contato.html`, `entrega.html`, `garantia.html`) não possuem imagens below-fold

## Backlog (pendente)

### Baixa prioridade
- ⏳ **COD-05** — trocar `TextField(max_length=500)` por `CharField(max_length=500)` em `Pedido.observacoes`
- ⏳ **MOD-03** — `db_index=True` em `Pedido.forma_pagamento`
- ⏳ **CFG-02** — `--workers 2` no Gunicorn (após Redis estável em produção)
- ⏳ **TPL-04** — substituir `style="width:Npx;height:Npx"` em SVGs por classes CSS
