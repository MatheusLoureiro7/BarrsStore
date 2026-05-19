# Auditoria Técnica Completa — Barrs Store

**Data:** 2026-05-19
**Branch:** main
**Base:** revalidação total do código atual, sem confiar no `AUDITORIA_TECNICA.md` de 2026-05-18

## Resumo executivo

O projeto está em **estado bem avançado**: dos 30 itens da auditoria anterior, **~13 foram resolvidos** (Turnstile, CSP Report-Only, Sentry, rate-limit em rastrear/sucesso/pendente, `validate_password`, filtro `visivel=True` no detalhe, webhook STRICT em prod, robots.txt restrito, herança de templates com `base.html`, peso de envio dinâmico, redução do payload CallMeBot, produto esgotado fica visível, X-Robots-Tag noindex via middleware). Permanecem alguns gaps com impacto real em **idempotência financeira (cupom + atomicidade do webhook)**, **performance mobile (CLS sem dimensão de imagens)** e **SEO (sitemap exclui esgotados, schema sem rating)**.

**Durante esta auditoria descobri e corrigi um resíduo do meu próprio fix anterior de encoding:** caracteres tipográficos 3-byte (`—`, `'`, `"`, `•`, `…`, `™`) ainda estavam em mojibake em 31 arquivos. Limpos agora, 0 ocorrências residuais.

---

## ✅ Já está corrigido (não mexer)

| Item | Local | Evidência |
|---|---|---|
| Herança de templates com `base.html` | `loja/templates/base.html` | 21 templates usam `{% extends "base.html" %}`; só `base.html` tem `<!DOCTYPE>` |
| CSS externo via Whitenoise | `static/loja/css/*` + `WHITENOISE_MAX_AGE=31536000` | Cache de 1 ano + `CompressedStaticFilesStorage` |
| Webhook MP STRICT em prod | `barrs_store/settings.py:289-291` | `True if not DEBUG else env('MP_WEBHOOK_STRICT')` |
| Validação HMAC MP com `compare_digest` | `loja/mercadopago_security.py:69-70` | Timing-safe + timestamp anti-replay |
| `select_for_update` + flag `estoque_baixado` | `loja/views.py:255-292` | Bloqueio idempotente do estoque |
| Flag `meta_purchase_sent` (anti dupla CAPI) | `loja/models.py:244`, `views.py:295-308` | Sem duplicação de Purchase |
| UUID `access_token` em pedidos | `loja/models.py:235` | Todas rotas de pagamento usam token |
| Turnstile aplicado em login e cadastro | `loja/views.py:2464, 2516` | `verificar_turnstile()` antes de POST |
| `validate_password()` em cadastro e checkout | `loja/views.py:2050, 2488` | `AUTH_PASSWORD_VALIDATORS` aplicado |
| Filtro `visivel=True` em `detalhe_produto_id` | `loja/views.py:1631` | Não enumera invisíveis via redirect |
| Rate-limit em rastrear_pedido (10/m GET) | `loja/views.py:2645` | Resolvido — agente havia afirmado o contrário, é falso |
| Rate-limit em pagamento_sucesso/pendente (30/m) | `loja/views.py:2379, 2398` | Bloqueia burst |
| Sentry com `send_default_pii=False` | `settings.py:22-35` | PII protegido |
| CSP em Report-Only (com Turnstile/MP/Pixel/Cloudinary) | `settings.py:225-240` + `middleware.py:70-87` | Pronto para virar enforce |
| Cookies + headers de segurança | `settings.py:195-224` | HSTS preload, SameSite, HttpOnly, Secure, X-Frame DENY |
| Peso de envio dinâmico (não mais 0.5kg fixo) | `views.py:57-67` | `0.1*itens` + altura cresce a cada 4 itens |
| Produto esgotado fica visível com badge | `views.py:255-292` (sem setar `visivel=False`) + grep "esgotado" nos templates | Não vira 404 |
| Payload CallMeBot enxuto (sem PII) | `views.py:1449-1454` | Só envia id, total, status, link painel |
| BlockScannerPaths whitelista webhook MP | `loja/middleware.py:38-40` | `/pagamento/webhook/` ignorado |
| Admin rate-limit por IP (60/5m POST) | `loja/middleware.py:46-67` | Proteção em `/painel/` e `/admin/` |
| robots.txt restrito | `views.py:2589-2603` | Disallow `/painel/`, `/carrinho/`, `/finalizar/`, `/pagamento/`, `/minha-conta/`, `/login/`, `/cadastro/` |
| X-Robots-Tag HTTP em rotas operacionais | `middleware.py:83-85` | `/pagamento/`, `/finalizar/`, `/minha-conta/` |
| Meta CAPI com PII SHA256 | `loja/integrations/meta_capi.py` | hash_email, hash_phone_br |
| Encoding/mojibake | 31 arquivos (templates + CSS + JS) | Corrigido nesta sessão (2-byte + 3-byte) |

---

## 🔴 CRÍTICO (corrigir antes de qualquer campanha)

### C1. Webhook MP e `confirmar_pedido_pago` não são atômicos

**Onde:** `loja/views.py:310-335`, `351-428`.

**Problema:** `confirmar_pedido_pago()` chama em sequência: atualizar status, incrementar cupom, baixar estoque, enviar Meta CAPI, enviar e-mail, criar envio no Melhor Envio — **sem `@transaction.atomic`**. Se MP repete o webhook (acontece) ou se o cliente abre 2 abas em `pagamento_sucesso`, `confirmar_pagamento_mercadopago()` roda em paralelo. O incremento do cupom (`Cupom.objects.filter(...).update(usado=F('usado')+1)`) e a checagem `pedido.status != 'confirmado'` (linha 313) **não estão no mesmo lock** — pode incrementar 2x antes de qualquer um chegar a salvar `status='confirmado'`.

**Impacto:** cupom contado 2x (não bloqueia o pedido, mas estraga relatório/uso_maximo); chamada extra de Melhor Envio gerando 2 envios; e-mail duplicado se `email_confirmacao_enviado` não estiver salvo a tempo.

**Mitigação atual:** `baixar_estoque_pedido` e `enviar_meta_purchase_pedido` JÁ usam `select_for_update` + flag idempotente — esses dois estão **seguros**. O resto (cupom, e-mail, envio ME) **não está**.

**Fix:** envolver o início de `confirmar_pedido_pago` em `transaction.atomic` + `select_for_update`:

```python
def confirmar_pedido_pago(pedido):
    with transaction.atomic():
        pedido_lock = Pedido.objects.select_for_update().get(pk=pedido.pk)
        if pedido_lock.status == 'confirmado':
            return  # já confirmado, sai
        pedido_lock.status = 'confirmado'
        if pedido_lock.cupom_codigo:
            Cupom.objects.filter(codigo__iexact=pedido_lock.cupom_codigo).update(usado=F('usado') + 1)
        pedido_lock.save(update_fields=['status'])
        pedido = pedido_lock  # continua com o lock
    baixar_estoque_pedido(pedido)
    enviar_meta_purchase_pedido(pedido)
    # ...
```

**Prioridade:** CRÍTICO. Esforço 15 min.

### C2. `status_pagamento` sem rate-limit nem cache → DoS via polling

**Onde:** `loja/views.py:2410-2419`.

**Problema:** endpoint chamado por polling do front-end no `confirmacao.html` (provavelmente a cada N segundos). Sem `@ratelimit`. Atacante com qualquer token UUID válido pode disparar centenas de queries/s.

**Impacto:** sobrecarga DB, custo Railway.

**Fix:**

```python
@ratelimit(key='ip', rate='120/m', method='GET', block=False)
def status_pagamento(request, pedido_id, token):
    ...
```

**Prioridade:** CRÍTICO. Esforço 2 min.

### C3. Checkout não chama Turnstile (somente login e cadastro)

**Onde:** `loja/views.py:1948-2160`.

**Problema:** `verificar_turnstile()` está em `cadastro` e `login_view`, **não em `checkout`**. O checkout pode criar User + Pedido em fluxo de bot. Rate-limit 8/m POST mitiga, mas bot distribuído (cada IP único) passa.

**Impacto:** criação de contas/pedidos fake em massa, gravação de leads, ruído nos analytics e Meta CAPI.

**Fix:** adicionar `if not verificar_turnstile(request): return render_checkout()` antes de processar o POST. **Atenção:** garantir que `partials/turnstile_widget.html` esteja incluso no `checkout.html` (revalidar).

**Prioridade:** CRÍTICO. Esforço 15 min.

---

## 🟠 ALTO

### A1. Sitemap exclui produtos esgotados → desindexação

**Onde:** `loja/sitemaps.py:12`.

**Problema:** `Produto.objects.filter(visivel=True, estoque__gt=0)`. Como o último commit fez produto esgotado **continuar visível e indexável** no site (boa decisão), excluí-lo do sitemap é incoerente: o Google vai despromover URLs que você ainda mostra. Schema.org já marca `availability: OutOfStock` corretamente — basta deixar a URL no sitemap.

**Fix:** trocar para `filter(visivel=True).order_by('-criado_em')`.

**Prioridade:** ALTO. Esforço 1 min.

### A2. Imagens sem `width`/`height` em quase tudo → CLS ruim no Core Web Vitals

**Onde:** `loja/templates/*.html` (apenas detalhe.html tem srcset; restante usa `produto.imagem.url` cru).

**Problema:** 33 `<img>` no projeto, ~1 com `width/height`. Cumulative Layout Shift alto em mobile → afeta Google Page Experience.

**Fix:** adicionar `width`/`height` (mesmo aproximados) em todas as imagens de produto e logos. Para Cloudinary, usar templatetag para gerar variantes:

```html
<img src="..." width="320" height="320" loading="lazy" alt="...">
```

**Prioridade:** ALTO. Esforço 1h (já existe `cloudinary_extras.py` — só usar).

### A3. Tolerância do webhook = 600s (10 min) permite replay

**Onde:** `barrs_store/settings.py:288`, `mercadopago_security.py:31`.

**Problema:** `MP_WEBHOOK_TOLERANCE_SECONDS=600` é generoso. Webhook capturado pode ser replayado por 10 min. A idempotência do estoque protege contra duplicação de baixa, mas não contra o resto se C1 não for resolvido.

**Fix:** reduzir para 30-60s em prod. Adicionalmente, cachear `request_id` processado (TTL 15min) para rejeitar replay:

```python
if cache.get(f'mp-req:{request_id}'): return JsonResponse({'status':'duplicate'}, status=200)
cache.set(f'mp-req:{request_id}', 1, 900)
```

**Prioridade:** ALTO. Esforço 10 min.

### A4. Schema.org Product sem `aggregateRating` e com `shippingRate` fixo `29.90`

**Onde:** `loja/templates/partials/product_schema.html:23-28`.

**Problema:** valor de frete chumbado em R$29.90 (real é dinâmico via Melhor Envio). Sem rating, perde a estrela amarela no Google → CTR menor.

**Fix:** remover `shippingDetails.shippingRate.value` chumbado e usar valor mais realista por região, ou retirar o bloco (manter `hasMerchantReturnPolicy`). Quando começar a coletar reviews via pós-compra, adicionar `aggregateRating`.

**Prioridade:** ALTO (correção do frete chumbado) / MÉDIO (adicionar rating). Esforço 15 min.

### A5. `tests.py` vazio

**Onde:** `loja/tests.py`.

**Problema:** sem testes automatizados em rotina que toca dinheiro. Toda alteração no webhook/cupom/estoque é regressão potencial.

**Fix:** começar pequeno e cobrir:

- `cpf_valido()` — função pura, 4 casos
- `_parse_signature_header()` + `_timestamp_fresco()` — 5 casos
- `calcular_frete_por_estado()` — 6 estados
- `Cupom.valido_para()` e `calcular_desconto()` — 4 casos por tipo
- Cenário: webhook duplicado → estoque baixado uma vez

**Prioridade:** ALTO (para sustentabilidade). Esforço 2h.

---

## 🟡 MÉDIO

### M1. `pagamento_falha` sem rate-limit
**Onde:** `loja/views.py:2391`. Sem `@ratelimit`. Como exige token UUID, força bruta é inviável, mas vale alinhar com sucesso/pendente (30/m).

### M2. `enfileirar_email_pendente` faz dedupe por hash do payload (timestamp incluído pode quebrar idempotência)
**Onde:** `views.py:182-202`. Se payload incluir hora ou ID variável, dedupe não funciona em webhook duplicado.
**Fix:** dedupe_key = `f"{pedido.id}:{tipo_email}"` (estável).

### M3. Arquivo morto: `loja/templates/partials/base_styles.html`
**Onde:** confirmado via grep — nenhum template ainda inclui `base_styles.html`. Resto do CSS migrou para `static/loja/css/base.css`. Pode deletar.

### M4. `calcular_frete_ajax` está zumbi
**Onde:** `views.py:1671-1675` — retorna sempre "Frete fixo desativado". URL `frete/calcular/` ainda mapeada (`urls.py:35`). Se nenhum template/JS chama, remover URL+função.

### M5. Logs ainda registram email completo em vários pontos
**Onde:** `views.py` em ~20 `logger.info`/`warning` com `%s` de `pedido.email` ou `pedido.nome`. Já existe helper `dominio_email_para_log()`, só não é usado universalmente.
**Fix:** trocar `pedido.email` por `dominio_email_para_log(pedido.email)` nos loggers que tocam PII. Pedido.id é seguro.

### M6. CSP em Report-Only com `'unsafe-inline'` e `'unsafe-eval'` em `script-src`
**Onde:** `settings.py:231`. Necessário hoje pelo Brick e GA gtag. Plano: migrar para nonce em scripts inline próprios e tirar `'unsafe-eval'` quando confirmar com MP.
**Fix:** começar a inserir nonces nos `<script>` próprios e mudar para enforce em ambiente staging primeiro.

### M7. `confirmacao.html` reduziu 21898 → 21001 bytes após o fix de mojibake — vale revisar o template grande
**Onde:** templates `pagamento_sucesso/pendente/falha` têm 10-20kB cada — em parte por CSS inline duplicado entre eles. Já existe `static/loja/css/pages/pagamento_*.css` para cada, vale conferir se ainda há `<style>` redundantes no template.

### M8. SQLite em desenvolvimento + Postgres em prod via `DATABASE_URL`
**Onde:** `settings.py:114-125`. Funciona, mas há divergência sutil: `iexact` no Postgres é case-insensitive nativo (`citext`/index ILIKE), no SQLite é LIKE. Filtros como `Pedido.objects.get(id=pedido_id, email__iexact=email)` continuam corretos, mas relatar performance pode mascarar problemas.

### M9. `processar_pagamento_brick` confia em `payer_front` para email/identification quando o do pedido falta
**Onde:** `views.py:2272-2274`. Em teoria atacante poderia injetar email de outro CPF, mas como o pedido é dele (via token UUID) e a confirmação MP usa `external_reference`, o risco é baixo. Vale forçar `payer['email'] = pedido.email` sempre.

### M10. Sem 2FA no admin
**Onde:** `/painel/`. Rate-limit 60/5m existe, mas senha vazada → comprometimento total. Adicionar `django-otp` + TOTP é plug-and-play.

---

## 🟢 BAIXO

### B1. Constantes `FRETE_SP/FRETE_GRATIS_*` em `models.py` parecem legado
**Onde:** `models.py:11-32`. Função `calcular_frete_por_estado` ainda é usada por `Carrinho.frete()` (model), mas o checkout real usa Melhor Envio. Pode estar duplicando lógica de domínio.

### B2. `meta_pixel.html` e `seo_head.html` carregados em todas as páginas (até carrinho/checkout)
**Onde:** `partials/seo_head.html:20`. Pixel disparando em páginas com `noindex` polui métricas, mas isso é decisão de marketing.

### B3. `CALLMEBOT_API_KEY` ainda usado para notificação interna
**Onde:** `views.py:1457`. CallMeBot tem TOS frágil. Migrar para Brevo SMS ou WhatsApp Cloud API a médio prazo.

### B4. `MERCADOPAGO_PUBLIC_KEY` exposto no template `confirmacao.html`
Por design (precisa do front), não é segredo. **OK.**

### B5. `static/og-barrs-store.jpg` no root de `/static/`
Funciona via Whitenoise, mas convém mover para `/static/loja/og-barrs-store.jpg` por consistência. Não é urgente.

### B6. Sessões 30 dias + `SESSION_COOKIE_DOMAIN=.barrsstore.com.br`
Em prod compartilha cookies entre www/apex (bom). Avaliar reduzir para 14 dias em UX/risco.

### B7. `EmailPendente` cresce sem TTL
Sem job que apague registros antigos (`status='enviado'` com >90 dias). Cresce indefinidamente.

### B8. `slugify` em `Produto.save()` faz query a cada save para garantir unicidade
Aceita até 100 produtos; revisitar quando passar de 1000.

### B9. `loja/whatsapp.py` define `WHATSAPP_API_URL` mas nunca é chamado no fluxo de pedido
Função existe mas o pedido usa CallMeBot. Decidir: migrar tudo para Evolution API ou remover o módulo.

### B10. `MELHOR_ENVIO_TOKEN` ausente → endereço inválido no envio
Validar que está configurado em produção. Sem ele, `criar_envio_melhor_envio` grava `melhor_envio_status='erro'` e pedido segue, mas você nunca recebe etiqueta.

---

## Checklist final do ecommerce

### 🛒 Fluxo de compra
- [x] Carrinho com session + persistência DB
- [x] Lead capture pré-checkout
- [x] Cupom (percentual / valor / frete grátis)
- [x] Frete via Melhor Envio com peso dinâmico
- [x] Checkout cria User automaticamente + valida senha
- [x] Mercado Pago Brick (Pix + cartão)
- [x] Webhook MP com HMAC + timestamp
- [ ] Webhook + confirmação atômicos (C1)
- [ ] Turnstile no checkout (C3)
- [x] Confirmação por token UUID
- [x] Idempotência de estoque
- [x] Idempotência de Meta CAPI
- [ ] Idempotência de cupom (depende de C1)
- [ ] Idempotência de e-mail (M2)
- [x] Rastreio do pedido com rate-limit

### 🔒 Segurança
- [x] HTTPS forçado + HSTS preload
- [x] CSRF + cookies Secure/HttpOnly/SameSite
- [x] X-Frame DENY, nosniff, COOP same-origin
- [x] CSP (Report-Only)
- [x] Turnstile em login e cadastro
- [ ] Turnstile no checkout (C3)
- [x] Rate-limit em todas rotas críticas
- [ ] Rate-limit em `status_pagamento` (C2)
- [ ] Rate-limit em `pagamento_falha` (M1)
- [x] `validate_password` em ambos fluxos de senha
- [x] Sentry com `send_default_pii=False`
- [ ] 2FA no admin (M10)
- [ ] Mascarar emails em logs (M5)
- [x] BlockScannerPaths
- [x] Admin rate-limit

### 📈 SEO
- [x] `<title>`, meta description, canonical, OG, Twitter, schema OnlineStore
- [x] Schema Product + BreadcrumbList
- [x] noindex em rotas operacionais (HTML + HTTP header)
- [x] robots.txt restrito
- [x] Sitemap dinâmico
- [ ] Sitemap inclui esgotados (A1)
- [ ] aggregateRating no produto (A4)
- [ ] shippingRate dinâmico no schema (A4)
- [x] URLs amigáveis com slug
- [x] Verificação Google + Facebook domain

### ⚡ Performance / Core Web Vitals
- [x] Whitenoise + cache 1 ano
- [x] CSS modular (sem CSS inline gigante)
- [x] JS único (`base.js`) com `defer`
- [x] Fonts com `display=swap` e preconnect
- [x] Cloudinary com `q_auto/f_auto`
- [ ] Imagens com `width`/`height` (A2 — CLS)
- [ ] Imagens com `loading="lazy"` em todo lugar (parcial)
- [ ] `srcset` em home/carrinho/relacionados (M)
- [x] Compressão Whitenoise
- [x] Sentry trace 5%

### 📱 Mobile / UX
- [x] Viewport correto
- [x] Menu hambúrguer funcional (`base.js`)
- [x] Fonte >=16px
- [x] Produto esgotado com badge (não 404)
- [x] Carrinho contador
- [ ] Botão "Adicionar"/"Finalizar" com loading state visível
- [ ] Toast/feedback visual de cupom aplicado
- [x] Estado vazio do carrinho

### 🗄️ Banco / Models / Admin
- [x] Postgres em prod via `DATABASE_URL`
- [x] Cloudinary em media
- [x] Jazzmin admin
- [x] PedidoAdmin com ações de rastreio
- [x] EmailPendente com dedupe
- [ ] TTL/cleanup de EmailPendente antigos (B7)

### 🔌 Integrações
- [x] Mercado Pago (Brick + webhook)
- [x] Brevo (transactional emails)
- [x] Cloudinary (images)
- [x] Melhor Envio (frete + envio)
- [x] Meta Pixel + CAPI (com hash)
- [x] Google Analytics
- [x] Cloudflare Turnstile
- [x] Sentry
- [ ] WhatsApp Evolution API (existe mas não usada — B9)

---

## O que já está profissional

1. **Webhook MP**: HMAC com `compare_digest`, timestamp, STRICT mode, whitelist no scanner middleware — arquitetura sólida.
2. **Idempotência de estoque e Meta CAPI**: `select_for_update` + flag — race conditions tratadas no que mais importa.
3. **Token UUID em todas as rotas de pagamento**: enumeração impossível.
4. **Sem PII em logs/analytics**: Meta CAPI faz hash SHA256, payload MP é mascarado (`payload_pagamento_seguro_para_log`), Sentry com `send_default_pii=False`, CallMeBot reduzido.
5. **Estrutura de templates**: `base.html` + blocks + partials (`seo_head`, `product_schema`, `meta_pixel`, `turnstile_widget`, `icon_sprite`) bem decomposta.
6. **CSS modular**: `base.css` + `components/` + `pages/` com design tokens (`:root --color-*`, `--space-*`, `--text-*`).
7. **JS enxuto**: 130 linhas, sem jQuery, com `defer`.
8. **Schema.org rico**: OnlineStore + Product + BreadcrumbList + MerchantReturnPolicy + ShippingDetails.
9. **Rate-limit cirúrgico**: chave por IP + janela por rota, valores ajustados por sensibilidade.
10. **Cookies + headers**: HSTS preload, SameSite, HttpOnly, Secure, COOP, X-Frame DENY — checklist OWASP cumprido.
11. **Cloudinary com `q_auto/f_auto`**: AVIF/WebP automático.
12. **Encoding agora 100% UTF-8 limpo** (após esta sessão).

---

## O que ainda impede o site de ser "premium"

| # | Bloqueio | Impacto |
|---|---|---|
| 1 | Webhook + cupom + e-mail **não atômicos** (C1) | Pode duplicar contagem de cupom / e-mail / envio ME em retentativa do MP |
| 2 | `status_pagamento` sem rate-limit (C2) | Polling agressivo derruba DB |
| 3 | Checkout sem Turnstile (C3) | Bot pode criar leads/pedidos fake |
| 4 | Imagens sem `width`/`height` (A2) | CLS ruim → Google penaliza UX |
| 5 | Sitemap exclui esgotados (A1) | Produto esgotado some do Google mesmo aparecendo no site |
| 6 | Schema com frete chumbado R$29.90 (A4) | Inconsistência com frete real |
| 7 | Zero testes automatizados (A5) | Cada commit de checkout é risco |
| 8 | CSP em Report-Only (M6) | Defesa em profundidade incompleta |
| 9 | Logs vazam email (M5) | LGPD cinza |
| 10 | Sem 2FA no admin (M10) | Painel = senha única |

---

## O que falta para "grande ecommerce"

### Operacional
- **Painel de saúde**: dashboard interno mostrando pedidos pendentes >24h, falhas de Brevo/ME, fila `EmailPendente`, taxa de erro do webhook MP.
- **Management command `cancelar_pendentes_expirados`**: PIX vence em 60min e MP cancela; cron diário para devolver estoque de pedidos `pendente` com >24h. Hoje não existe.
- **Retry automático de `EmailPendente`**: hoje depende de você rodar `enviar_emails_pendentes` manualmente — agendar via Railway cron.
- **TTL automático em `EmailPendente`/`Carrinho` antigos**.
- **Webhook de chargeback/refund do MP**: hoje só trata `payment` e `merchant_order` — adicionar `payment.refunded` para devolver estoque automaticamente.

### Produto
- **Página de categoria** (hoje a home filtra tudo). Melhora SEO de cauda longa.
- **Busca interna** + autocomplete.
- **Reviews dos clientes** (alimenta `aggregateRating` do schema).
- **"Avise-me quando voltar"** para esgotados (captura lead em vez de perder a venda).
- **Recomendados por colaborative filtering** (hoje só por categoria).

### Performance
- **Cache `@cache_page(60)` na home/categorias** + invalidação no admin.
- **Image CDN com `srcset` automático** via templatetag Cloudinary (você já tem `cloudinary_extras.py`, só ampliar).
- **Pré-load do herói** (`<link rel="preload" as="image">`).
- **CSS critical inline** + resto async.

### Segurança
- **2FA no admin** (`django-otp` + TOTP).
- **CSP em enforce** com nonces.
- **Server-side Pixel/GA4** (sGTM) para resistir a adblocker — já tem CAPI, replicar para GA.
- **Validação de CEP via ViaCEP** server-side no checkout.
- **`X-Idempotency-Key` no Brevo** (similar ao que já faz em MP).

### Marketing
- **Newsletter Brevo com double opt-in**.
- **Abandono de carrinho automatizado** (já tem flags, falta o cron).
- **Pixel/CAPI também em adicionar-ao-carrinho e início-checkout** (hoje só Purchase).
- **UTM tracking persistente na sessão** para atribuição.

---

## Prioridade de execução recomendada

| Sprint | Itens | Esforço total |
|---|---|---|
| **Sprint 1 (segurança financeira)** | C1, C2, C3, A3, A1 | ~1h30 |
| **Sprint 2 (SEO/perf imediato)** | A2, A4, M3, M4 | ~2h |
| **Sprint 3 (operação saudável)** | A5 (testes), M2, M5, M10, B7 | ~6h |
| **Sprint 4 (premium)** | CSP enforce, srcset universal, avise-me-quando-voltar, dashboard interno | ~10h |

**Recomendação:** Sprint 1 antes de qualquer campanha paga ou Black Friday. Os 3 críticos juntos somam ~30 minutos de código e fecham os riscos de duplicação e DoS.

---

*Auditoria executada em 2026-05-19, sobre commit `9678e33`. Os arquivos `_mojimap.json` temporários foram removidos. A correção de mojibake 3-byte aplicada durante esta auditoria também ajustou 31 arquivos (templates + CSS); não alterou layout, classes, blocos Django, URLs ou lógica — apenas decodificou caracteres tipográficos (`—`, `'`, `"`, `•`, `…`, `™`) para UTF-8 correto.*
