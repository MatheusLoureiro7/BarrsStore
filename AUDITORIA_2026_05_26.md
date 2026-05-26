# 🔍 AUDITORIA TÉCNICA — BARRS STORE

**Data:** 2026-05-26
**Escopo:** Análise completa pós-refinamentos premium (UI/UX, performance, segurança, MP, conversão)
**Metodologia:** Leitura direta de código — `settings.py`, `views.py` (2.874 linhas), `models.py`, `admin.py`, `middleware.py`, `mercadopago_security.py`, templates e configurações de deploy.

---

## 1️⃣ SEGURANÇA — **9 / 10**

### ✅ O que está FORTE (acima da média do mercado)

| Camada | Implementação |
|---|---|
| `DEBUG` | Default `False`; `SECRET_KEY` ausente em prod → `ImproperlyConfigured` (não permite boot inseguro) |
| HTTPS | `SECURE_SSL_REDIRECT=True` em prod, `SECURE_PROXY_SSL_HEADER`, HSTS 1 ano com preload + subdomains |
| Cookies | `HttpOnly + Secure (prod) + SameSite=Lax` em session/csrf; `SESSION_COOKIE_DOMAIN='.barrsstore.com.br'` (compartilha www/apex) |
| Clickjacking | `X_FRAME_OPTIONS=DENY` + `frame-ancestors 'none'` no CSP |
| CSRF | `CSRF_TRUSTED_ORIGINS` configurado; único `@csrf_exempt` é no webhook MP (correto) |
| Webhook MP | HMAC SHA-256 com **`hmac.compare_digest`** (timing-safe), validação de timestamp (300s), dedupe por `x-request-id` (24h), modo strict em prod |
| Idempotência | `select_for_update` em estoque/cupom/status; flags `estoque_baixado`, `meta_purchase_sent`, `email_*_enviado` |
| Brute force | Custom `AdminRateLimitMiddleware` (60/5min) + `@ratelimit('5/m')` em login/cadastro + Cloudflare Turnstile |
| 2FA | `django_otp` instalado (TOTP + tokens estáticos) — pronto para staff |
| Scanners | `BlockScannerPathsMiddleware` (403 silencioso em `/wp-admin`, `.sql`, etc.) |
| Acesso pedido | `access_token = UUIDField` — URLs de confirmação/pagamento não enumeráveis |
| XSS | Único `\|safe` é em JSON-LD já escapado (`_clean_seo_text` + replace `<>&`) |
| Senhas | 4 validadores Django (min 8, common, numeric, similarity) |
| Secrets | `.env` gitignored ✅; só `.env.example` em git |

### ⚠️ RISCOS MÉDIOS (não bloqueia subida, mas deve resolver)

1. **CSP em `Report-Only` por padrão**
   `CSP_ENFORCE` default = `False`. Em prod, sem `CSP_ENFORCE=True` no Railway, CSP é **apenas observação** — XSS pode passar. → **Setar `CSP_ENFORCE=True` no Railway**.

2. **`'unsafe-eval'` no `script-src`**
   Necessário para SDK do Mercado Pago. Tradeoff aceito, mas é vetor real de injection bypass.

3. **`'unsafe-inline'` no `style-src`**
   Permite todos os `style="..."` inline. Várias páginas usam (ex: `<a style="color:inherit"...>` no footer). Não-crítico, mas reduz força do CSP.

4. **`WHITENOISE_USE_FINDERS=True` default**
   Em prod deve ser `False` (executa busca no filesystem a cada static request). → Setar `WHITENOISE_USE_FINDERS=False` no Railway.

5. **Carrinho/ItemCarrinho editáveis no admin**
   Não é XSS, mas edição manual pode quebrar consistência. → Considerar `readonly_fields` ou `has_change_permission=False`.

### ⚠️ RISCOS BAIXOS

- Admin em `/admin/` (padrão; rate limit compensa)
- `SESSION_COOKIE_AGE = 14 dias` (escolha de UX consciente)
- Sem skip-to-content link (a11y)

---

## 2️⃣ PERFORMANCE — **7.5 / 10**

### ✅ FORTE

- Cache em `count()` da home (60s), categorias (5min), cliques (cron flush) — evita 1 UPDATE por visita
- `select_related('produto')` em carrinho/checkout/baixa de estoque (8 ocorrências verificadas)
- Webhook MP com dedupe (não consulta API duplicado)
- Hero com `fetchpriority="high"` (LCP)
- Cards com `loading="lazy"` + `decoding="async"`
- Cloudinary `q_auto/f_auto` + srcset 360/520/760w
- Whitenoise + `CompressedStaticFilesStorage` (gzip+brotli automático)
- Sentry hook com `traces_sample_rate` configurável

### 🔴 GARGALOS REAIS

1. **CRÍTICO PARA LCP — CSS duplicado `<link>` + `inline_static`**
   Em `base.html` linhas 14-18: **carrega o mesmo `base.css` via `<link>` E embute inline via `{% inline_static %}`**. O mesmo em `home.css`. Consequência: ~140KB de CSS embutido no HTML **mais** o navegador baixando o `<link>`. Primeiro pageview paga DUPLA largura.
   → **Decidir**: ou inline (remove `<link>`) ou link (remove `inline_static`). Recomendo manter inline (FCP imediato) e remover o `<link>`.

2. **`home.css` = 99KB** (cresceu por acúmulo de overrides nesta sessão)
   Tem 4+ blocos `.product-card__body` redefinidos, 6 overrides de `.ph-todas .product-grid`, etc. Funciona, mas é tecnicamente bagunçado. Refator opcional → 30-40KB.

3. **N+1 latente em `checkout` linha 2186**
   ```python
   for item in itens:  # <— sem select_related
       ItemPedido.objects.create(produto=item.produto, ...)
   ```
   Insignificante (<10 itens por checkout), mas detectável em django-silk.

4. **Arquivos lixo em `static/`**
   `static/loja/css/pages/home.css.tmp.py` e `home.css.tmp2.py` — vão para o build do whitenoise. **Remover**.

---

## 3️⃣ MERCADO PAGO / WEBHOOK — **9.5 / 10**

Esta é a parte **melhor implementada do projeto**. De longe.

### ✅ EXCELENTE

- **HMAC timing-safe** com `hmac.compare_digest`
- **Tolerância de timestamp** configurável (300s default)
- **Modo strict obrigatório em produção** (`MERCADOPAGO_WEBHOOK_STRICT = True if not DEBUG`)
- **Dedupe por `x-request-id`** via `cache.add(..., 24h)` atômico (MP reentrega — você ignora)
- **`confirmar_pedido_pago` é blindado**:
  ```python
  with transaction.atomic():
      pedido_lock = Pedido.objects.select_for_update().get(pk=...)
      if pedido_lock.status != 'confirmado':  # ← idempotente
          ...
  ```
- **Guarda crítica contra webhook tardio**: se chega `cancelled`/`rejected` mas pedido já está `confirmado`, ignora (evita reverter pedido pago)
- **`refunded`/`charged_back` → ERROR log** (alerta humano via Sentry)
- **Pedido sem direct reference** → fallback via merchant_order
- **Estoque baixado APENAS UMA VEZ** (flag `estoque_baixado` + select_for_update)
- **Meta CAPI Purchase enviado UMA VEZ** (flag `meta_purchase_sent`)
- **Retorna HTTP 200 sempre** (não causa retry storm em MP)

### ⚠️ CHECKLIST DE ENV (sem isso, MP quebra)

- `MP_ACCESS_TOKEN` (produção, não `TEST-...`)
- `MP_PUBLIC_KEY` (produção)
- `MP_WEBHOOK_SECRET` (gerar no painel MP > Webhooks)
- `MP_WEBHOOK_TOLERANCE_SECONDS=300` (opcional)

---

## 4️⃣ ECOMMERCE / CONVERSÃO — **9 / 10**

### ✅ COMPLETO

- Recuperação de **carrinho abandonado** (cron `enviar_carrinhos_abandonados`)
- Jornada pós-compra (5 e-mails: `email_poscompra_1..5_enviado`)
- E-mail de pagamento pendente (cron, dispara após 20min)
- Cupons funcionais (% / R$ fixo / frete grátis)
- Frete por região + Melhor Envio (criação automática de etiqueta no `confirmado`)
- Meta Pixel **+ CAPI server-side com dedup `event_id`** (matching avançado)
- UTM/GCLID/FBCLID capturados last-touch + persistidos em `Pedido.origem_utm`
- Schema.org JSON-LD (Product) — bom para Google Shopping
- Selos de confiança no footer
- Newsletter (frontend-only, OK)
- "Em estoque" / "Últimas unidades" / "Esgotado" — gatilho de escassez

### ⚠️ MELHORIAS

- Checkout cria `Pedido` + `ItemPedido` em loop **sem** `transaction.atomic` envolvendo o conjunto. Se o loop quebrar no item 3 de 5, fica Pedido órfão com 2 itens. Adicionar `with transaction.atomic():` em volta.
- Em `pagamento_falha`, considerar mostrar opção "Pagar de novo" reusando o mesmo pedido (já tem o token).

---

## 5️⃣ DJANGO / BACKEND — **8.5 / 10**

### ✅ ORGANIZAÇÃO

- App único `loja/` (apropriado para o tamanho)
- Models bem indexados (`db_index=True` em `email`, `status`, `criado_em`, `atualizado_em`, etc.)
- 11 management commands (crons reais, não cargo cult)
- Sitemap dinâmico + robots.txt
- Logger com formato Railway-friendly
- 2FA com proxies traduzidos pt-br (esforço extra valorizado)
- Health endpoint `/painel/saude/`

### 🔴 LIMPEZA PENDENTE

- `AUDITORIA_2026_05_21_FINAL.md` (19KB) e `AUDITORIA_FINAL_2026_05_21_v2.md` (12KB) — soltos no root, sem `/docs`
- `static/loja/css/pages/home.css.tmp.py` e `home.css.tmp2.py` — lixo de iteração, virariam asset servido
- `AUDITORIA_2026_05_19.md` e `AUDITORIA_TECNICA.md` marcados como deleted em `git status`

---

## 6️⃣ MOBILE — **8.5 / 10**

✅ Hamburger nav com submenu, categoria horizontal escondida no mobile, sticky CTA no detalhe, cards 2 cols com row-gap maior, newsletter responsiva, touch targets ≥38px.

⚠️ Algumas linhas no `home.css` (gradient/blur) podem ter custo em devices low-end, mas dentro do tolerável.

---

# 📋 RELATÓRIO FINAL

## 🔴 LISTA DE PROBLEMAS CRÍTICOS (BLOQUEIA PROD)

**Nenhum.** Mas há uma **checklist de env vars no Railway** que, se não estiver, transforma silenciosamente coisas críticas em risco:

| Env | Por quê |
|---|---|
| `SECRET_KEY` | Sem ela, app não sobe (já enforced) |
| `DATABASE_URL` | Sem ela, cai em SQLite (cabum em prod) |
| `MP_WEBHOOK_SECRET` | Sem ela, webhook rejeita TUDO (modo strict ativo em prod) |
| `MP_ACCESS_TOKEN` + `MP_PUBLIC_KEY` | Sem elas, pagamentos não rolam |
| `CSP_ENFORCE=True` | Sem ela, CSP é só observação |
| `WHITENOISE_USE_FINDERS=False` | Sem ela, static lerdo |
| `ALLOWED_HOSTS` (se não usar default) | Sem ela, hosts não cobertos = `400 Bad Request` |
| `SENTRY_DSN` | Recomendado: visibilidade em prod |

## 🟡 MELHORIAS IMPORTANTES (depois de subir, antes de escalar)

1. **Remover duplicação `<link>` + `inline_static`** no `base.html` — economiza ~140KB/pageview
2. **Limpar `static/.../*.tmp.py`** (virarão asset)
3. **Mover `AUDITORIA_*.md` para `/docs`** ou deletar
4. **Envolver `Pedido + ItemPedido` em `transaction.atomic` no checkout**
5. **Refatorar `home.css`** (99KB com overrides duplicados → estimativa 35KB)

## 🟢 MELHORIAS OPCIONAIS

- Skip-to-content link (a11y AA)
- Carrinho admin readonly (defesa em profundidade)
- Trocar URL do admin de `/admin/` para algo opaco
- N+1 trivial em checkout linha 2186 → `itens.select_related('produto')`
- Migrar inline styles para CSP-friendly via nonces

## 📊 NOTA GERAL

| Eixo | Nota |
|---|---|
| **Segurança** | **9 / 10** — Faltam apenas confirmações de env vars |
| **Performance** | **7.5 / 10** — Penalizada pela duplicação CSS |
| **UX/UI Premium** | **8.5 / 10** — Refinamentos das últimas sessões valeram |
| **Conversão** | **9 / 10** — Recuperação, jornada, CAPI, schema, escassez — tudo presente |
| **Aparência premium** | **8.5 / 10** — Acima da média do nicho |
| **Estabilidade** | **9.5 / 10** — Idempotência e locks exemplares |

---

## ✅ VEREDITO

# **PODE SUBIR PARA PRODUÇÃO**

**Motivo técnico:** A arquitetura de pagamento está em nível de e-commerce sério (idempotência exemplar, HMAC timing-safe, dedupe de webhook, locks atômicos). A segurança Django está acima da média (HSTS preload, 2FA, rate limit, Turnstile, CSP configurado). O fluxo de conversão está completo (carrinho abandonado, CAPI server-side, jornada pós-compra). Não vejo **nada** que justifique adiar a subida.

**Condição absoluta antes do deploy:** valide a checklist de env vars do Railway (acima). Sem `MP_WEBHOOK_SECRET` em modo strict, **todo webhook será rejeitado em produção** — esse é o único cenário que pode te morder silenciosamente.

**O que NÃO precisa fazer agora:** refatorar `home.css`, mexer em CSP, trocar admin URL — tudo isso é refinamento técnico que não afeta o cliente final.

---

## 📦 ANEXO — Evidências usadas na auditoria

### Arquivos lidos
- `barrs_store/settings.py` (329 linhas)
- `loja/views.py` (2.874 linhas)
- `loja/models.py` (552 linhas)
- `loja/admin.py` (344 linhas)
- `loja/middleware.py` (126 linhas)
- `loja/mercadopago_security.py` (73 linhas)
- `loja/templatetags/inline_static.py`
- `loja/urls.py`
- Templates: `base.html`, `home.html`, `detalhe.html`, `partials/*.html`
- CSS: `base.css` (40KB), `pages/home.css` (99KB), `pages/detalhe.css` (18KB)

### Funções críticas verificadas
- `webhook_mercadopago` (linha 2528) — validação HMAC + dedupe + 200 always
- `confirmar_pagamento_mercadopago` (linha 543) — guard de status, fallback merchant_order
- `confirmar_pedido_pago` (linha 499) — select_for_update + cupom F() atomic
- `baixar_estoque_pedido` (linha 444) — lock + flag idempotente em Produto/TamanhoAnel
- `checkout` (linha 1988) — validação Turnstile + CPF + estoque + frete + cupom
- `home` (linha 1445) — cache count + cache categorias + partial AJAX para infinite scroll
- `validar_assinatura_mercadopago` — manifesto `id:X;request-id:Y;ts:Z;` + compare_digest
