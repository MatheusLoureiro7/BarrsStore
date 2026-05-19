# Auditoria Técnica — Barrs Store

Data: 2026-05-18
Escopo: análise técnica completa do projeto Django Barrs Store (sem alterar código). As recomendações estão classificadas por prioridade: **CRÍTICO**, **IMPORTANTE**, **MELHORIA**, **OPCIONAL**. Cada item descreve o problema, o impacto e uma sugestão segura e isolada.

> Nada foi alterado no projeto. Tudo aqui é diagnóstico + propostas para você aprovar uma a uma.

---

## Sumário geral

O projeto está em estado **bem avançado e saudável** para uma loja em estágio inicial:

- Stack moderno (Django 6.0.4, WhiteNoise, Cloudinary, Mercado Pago, Brevo, Meta CAPI).
- HTTPS, HSTS, cookies seguros e CSRF estão corretamente configurados em produção.
- Webhook do Mercado Pago valida assinatura HMAC com timestamp e modo `STRICT` ligado em produção.
- Estoque é decrementado dentro de transação com `select_for_update` e flag idempotente (`estoque_baixado`).
- Rate-limit por IP (`django-ratelimit`) em login, cadastro, checkout, cupom, lead, frete e brick MP.
- Middleware próprio bloqueia paths de scanner (`.sql`, `wp-admin`, `xmlrpc.php` etc.).
- Pedido tem `access_token` UUID para impedir enumeração.
- Pixel + CAPI funcionando com hash dos PIIs.

Os pontos abertos são todos resolvíveis com pequenas mudanças cirúrgicas — não exige refatoração.

---

## 🔴 CRÍTICO

### 1. Vazamento de PII para serviço externo (CallMeBot) no envio de WhatsApp do pedido
**Onde:** `loja/views.py` → `enviar_whatsapp_pedido` (linhas ~1385-1424).

**Problema:** o nome completo, telefone, email, endereço completo e total do pedido são enviados via HTTPS **GET** para `https://api.callmebot.com/whatsapp.php`. Esses dados ficam em logs do provedor terceiro e em cache de URLs (LGPD).

**Impacto:** vazamento de dados pessoais de cada cliente em serviço de terceiros sem contrato/DPA. Em caso de incidente o LGPD obriga notificação.

**Sugestão segura:**
- Reduzir o conteúdo da mensagem só para "novo pedido #ID, total R$ X. Veja em /painel/".
- Migrar para envio via Brevo SMS ou WhatsApp Cloud API (você já tem WHATSAPP_API_URL no settings, mas não está sendo usado).
- Adicionar `LGPD_CONSENT` lógico apenas onde houver consentimento explícito (já existe `aceita_whatsapp` no Carrinho — bom).

---

### 2. Rastreamento público de pedidos pode vazar dados pessoais
**Onde:** `loja/views.py` → `rastrear_pedido` (linhas ~2533-2550) e `loja/urls.py` (rota `/rastrear/`).

**Problema:** a rota permite consultar qualquer pedido só com `pedido_id` + `email` na query string, **sem rate-limit, sem CSRF (GET), sem CAPTCHA**. Permite tentativa de força bruta para descobrir pedidos a partir de um vazamento de emails. O template exibe (a confirmar) status, endereço e código de rastreio.

**Impacto:** enumeração de pedidos com emails vazados — expõe endereço, status e tracking.

**Sugestão segura:**
- Adicionar `@ratelimit(key='ip', rate='10/m', method='GET', block=True)` na view.
- Mostrar apenas status + rastreio + 3 últimos dígitos do CEP/cidade no template (já mascarado).
- Exigir também `cpf` (últimos 4 dígitos) além de email+pedido, OU enviar o link UUID por email em vez de form público.

---

### 3. Validação de senha mínima sem usar `validate_password()`
**Onde:** `loja/views.py` → `cadastro` (linha ~2391) e `checkout` (linha ~1959).

**Problema:** o cadastro/checkout valida só `len(senha) < 8`. Os `AUTH_PASSWORD_VALIDATORS` configurados no `settings.py` (CommonPasswordValidator, NumericPasswordValidator, UserAttributeSimilarityValidator) não são executados porque você cria o usuário direto com `User.objects.create_user(...)`.

**Impacto:** clientes podem usar senhas comuns ("12345678", "password", "barrsstore"), facilitando ataque por dicionário, especialmente em uma rota de login pública sem captcha.

**Sugestão segura (pequena):**
```python
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

try:
    validate_password(senha, user=user_temp)  # ou User(username=email, email=email)
except ValidationError as e:
    messages.error(request, ' '.join(e.messages))
    return render_checkout()
```
Adicionar nos 2 pontos. É 5 linhas, totalmente reversível.

---

## 🟠 IMPORTANTE

### 4. Sem `Content-Security-Policy` (CSP)
**Onde:** `barrs_store/settings.py`.

**Problema:** o site carrega scripts de Mercado Pago, Meta Pixel, Google Analytics, Cloudinary, fonts.googleapis. Sem CSP, qualquer XSS que escape do `escape` do Django pode injetar script de terceiros.

**Impacto:** defesa em profundidade contra XSS. Hoje você já tem `X_FRAME_OPTIONS=DENY` e `SECURE_CONTENT_TYPE_NOSNIFF`, falta CSP.

**Sugestão segura:** adicionar `django-csp` no requirements e configurar uma policy permissiva (somente os hosts atuais), começando em `Content-Security-Policy-Report-Only` antes de virar enforcement. Exemplo mínimo:
```python
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "https://sdk.mercadopago.com", "https://connect.facebook.net", "https://www.googletagmanager.com")
CSP_IMG_SRC = ("'self'", "data:", "https://res.cloudinary.com", "https://www.facebook.com")
CSP_STYLE_SRC = ("'self'", "'unsafe-inline'", "https://fonts.googleapis.com")
CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com")
CSP_CONNECT_SRC = ("'self'", "https://api.mercadopago.com", "https://www.facebook.com", "https://graph.facebook.com")
```

---

### 5. `detalhe_produto_id` redireciona para produtos invisíveis/sem estoque (enumeração)
**Onde:** `loja/views.py` (linhas 1562-1564).

**Problema:** `get_object_or_404(Produto, id=produto_id)` não filtra `visivel=True, estoque__gt=0`. O redirect aponta para o slug que ai sim filtra — mas o **301 já confirma a existência do produto invisível**. Permite enumerar SKUs internos.

**Impacto:** baixo, mas vaza catálogo interno (códigos `codigo_interno`, drafts).

**Sugestão segura:** adicionar `, visivel=True, estoque__gt=0` na query da função, ou usar `Http404` se não estiver visível.

---

### 6. Senha visível na URL/POST do checkout sem proteção adicional
**Onde:** `loja/views.py` → `checkout` (linhas 1950-1981).

**Problema:** o checkout cria conta + loga automaticamente. Se o email já existir e a senha estiver errada, **retorna mensagem "Este e-mail já tem cadastro" antes de pedir senha** — isso é **enumeração de usuários**.

**Impacto:** permite descobrir quais emails têm conta na loja. Útil para credential stuffing.

**Sugestão segura:** usar mensagem genérica: `"E-mail já cadastrado: digite sua senha correta para entrar."` (sem distinguir entre senha errada e usuário inexistente).

Já está parcialmente assim ("Este e-mail ja tem cadastro. Digite a senha correta..."), mas ainda revela que **existe** cadastro. Mudar para "Não foi possível validar suas credenciais." quando houver email existente e senha errada.

---

### 7. Webhook em modo `MERCADOPAGO_WEBHOOK_STRICT=False` ainda processa o pagamento
**Onde:** `loja/views.py` → `webhook_mercadopago` (linhas 2350-2354).

**Problema:** quando assinatura falha **e** o modo strict é falso, o webhook só loga warning e continua executando `confirmar_pagamento_mercadopago`. Isso é OK para dev, mas atacante pode forçar `MERCADOPAGO_WEBHOOK_STRICT=False` via descuido de configuração e disparar confirmações.

**Impacto:** baixo em produção (você já tem `STRICT=True` default em prod), mas vale travar.

**Sugestão segura:** em produção, recusar webhook se assinatura não puder ser validada **sempre** (independente da env var). Mantém STRICT só como flag para desligar o teste local.

Alternativa cirúrgica: trocar `if not DEBUG: MERCADOPAGO_WEBHOOK_STRICT = True` (forçado), em vez de depender da env var.

---

### 8. Sem CAPTCHA em rotas anti-fraude / lead
**Onde:** `loja/views.py` → `salvar_lead_cliente`, `salvar_contato_carrinho`, `cadastro`, `login_view`, `aplicar_cupom_ajax`.

**Problema:** rate-limit (10/m, 5/m) protege contra brute force, mas não contra bot distribuído. Cupons podem ser farmados.

**Impacto:** spam de leads no banco, tentativas de descobrir cupons por força bruta.

**Sugestão segura:** habilitar Cloudflare Turnstile (gratuito, invisível, sem cookies de consentimento extras) só em `login`, `cadastro` e `aplicar_cupom_ajax`. Sem mudar a UX dos formulários.

---

### 9. Pedido confirmado por `payment_id` da URL (sucesso/pendente)
**Onde:** `loja/views.py` → `pagamento_sucesso` / `pagamento_pendente` (linhas 2298-2324).

**Problema:** a URL `?payment_id=X` faz chamada para confirmar. A função `confirmar_pagamento_mercadopago` é segura porque consulta MP e checa `external_reference`, mas a chamada acontece mesmo com `payment_id` aleatório → enumeração + custo de chamadas à API MP. Não há rate-limit nessas duas views.

**Impacto:** baixo (não confirma pedido errado, mas faz queries inúteis na API MP — pode estourar quota).

**Sugestão segura:** `@ratelimit(key='ip', rate='30/m', method='GET', block=False)` apenas para limitar burst.

---

### 10. Caixa de envio fixa subestima volume real
**Onde:** `loja/views.py` → constante `CAIXA_ENVIO = {width:11,length:16,height:6,weight:0.5}` (linha 30).

**Problema:** todos os pedidos cotam frete com a mesma caixa, independente da quantidade de itens. Pedidos grandes vão cotar barato e cobrar a menos do cliente.

**Impacto:** perda financeira em pedidos com 5+ peças.

**Sugestão segura:** multiplicar peso por quantidade ou recalcular dimensões dinamicamente:
```python
peso_total = max(0.2, sum(0.1 * item.quantidade for item in carrinho.itens.all()))
```
Sem trocar a constante (mantém retrocompat).

---

## 🟡 MELHORIA

### 11. CSS inline gigantesco repetido nos templates
**Onde:** `home.html` (998 linhas), `detalhe.html` (890), `checkout.html` (892), `carrinho.html` (714).

**Problema:** cada página repete grande parte do CSS via `partials/base_styles.html` + estilos próprios inline. HTML fica pesado, sem aproveitar cache do browser entre páginas.

**Impacto:** primeira pintura e LCP mais lentos em mobile 3G/4G.

**Sugestão segura:** extrair CSS comum (`base_styles.html`) para `static/css/base.css` servido pelo WhiteNoise com cache de 1 ano. Mantém o resto inline por página. Reversível.

### 12. Falta paginação na home
**Onde:** `home` view + template.

**Problema:** todos os produtos visíveis são renderizados de uma vez. Hoje o catálogo é pequeno, mas com 50+ produtos a home começa a degradar.

**Sugestão segura:** `Paginator(produtos, 24)` + botão "Carregar mais" via querystring `?p=N`. Sem mudar o JS atual.

### 13. `robots.txt` libera tudo
**Onde:** `loja/views.py` → `robots_txt` (linhas 2485-2491).

**Problema:** `Allow: /` libera Google a indexar `/carrinho/`, `/finalizar/`, `/pagamento/...`, `/minha-conta/`, `/painel/`. Hoje você usa `noindex_context` em algumas (boa prática), mas dá tempo do bot bater nas páginas.

**Sugestão segura:** adicionar no robots.txt:
```
Disallow: /painel/
Disallow: /carrinho/
Disallow: /finalizar/
Disallow: /pagamento/
Disallow: /minha-conta/
Disallow: /login/
Disallow: /cadastro/
```

### 14. Produto fica `visivel=False` automaticamente quando estoque zera
**Onde:** `baixar_estoque_pedido` em `views.py` (linhas 176-178).

**Problema:** produto esgotado desaparece da loja em vez de ficar "Esgotado / Avise-me quando voltar". Perde oportunidade de captura de lead e ranking SEO (URL deixa de existir → 404).

**Sugestão segura (opcional):**
- Manter `visivel=True` mas exibir "esgotado" no template (já existe `produto.disponivel()`).
- Adicionar form simples "Me avise quando voltar" ligado a `Lead`.

### 15. Várias rotas usam slug como ID, mas a busca não tem index DB
**Onde:** `Produto.slug` é unique mas SQLite pode estar sem o índice esperado em prod (depende do PG).

**Sugestão:** confirmar que está em PostgreSQL em produção (Procfile sugere Railway com Postgres) e que `db_index=True` foi gerado. Em SQLite local não afeta.

### 16. Imagens não usam `srcset` / `sizes` para mobile
**Onde:** `home.html`, `detalhe.html`, `carrinho.html`.

**Problema:** desktop e mobile recebem a mesma imagem (Cloudinary entrega original via `produto.imagem.url`).

**Sugestão segura:** usar `cloudinary` transformations no template para gerar variantes (`w_400`, `w_800`, `w_1200`) e `srcset`. Reduz drasticamente o tráfego mobile.

### 17. Schema.org do produto sem `aggregateRating` / `review`
**Onde:** `partials/product_schema.html`.

**Problema:** sem rating, o snippet do Google não ganha estrela e tem CTR menor.

**Sugestão (opcional):** começar coleta de reviews pelo Brevo pós-compra (já existe `enviar_email_poscompra_4`) e expor rating no schema quando houver dados.

### 18. Admin (`/painel/`) sem 2FA
**Onde:** `barrs_store/urls.py`.

**Problema:** o admin do Django é o coração do ecommerce. Hoje só tem login + senha + rate-limit (60/5m no AdminRateLimitMiddleware). Não tem 2FA.

**Sugestão segura:** `django-otp` + TOTP (Google Authenticator). É plug-and-play e protege contra credential stuffing mesmo se a senha vazar.

### 19. Logs vazam emails completos / payloads MP
**Onde:** vários `logger.info` no `views.py` registram `pedido.email`, `pedido.nome`, `[BREVO] Resposta pedido %s: body=%s`.

**Problema:** logs do Railway são acessíveis por todo o time / podem virar exportação. Email completo é PII.

**Sugestão segura:** o helper `payload_pagamento_seguro_para_log` já faz isso para MP. Estender o padrão para outros logs: logar `pedido.id`, domínio do email (`@gmail.com`) e nada de body inteiro de Brevo. Mantém debug.

### 20. Sem testes automatizados de fluxo crítico
**Onde:** `loja/tests.py` está vazio.

**Problema:** quando você mexer em checkout ou webhook MP, não há regressão automatizada.

**Sugestão segura:** começar pequeno: testes de `cpf_valido`, `_parse_signature_header`, `calcular_frete_por_estado`, `Cupom.calcular_desconto`. São funções puras, fáceis de testar.

### 21. Templates não usam herança (`{% extends %}`)
**Onde:** todos os templates duplicam DOCTYPE, nav, footer, scripts.

**Problema:** manutenção fica difícil — qualquer mudança no header precisa ser feita em 15 arquivos.

**Sugestão segura (médio porte):** quando tiver tempo, criar `base.html` com `{% block content %}` e refatorar 1 página por vez. Pode esperar.

---

## 🟢 OPCIONAL

### 22. Adicionar `SECURE_REFERRER_POLICY = "same-origin"` para checkout
Hoje está `strict-origin-when-cross-origin`. Em páginas com Pix/MP, vale `same-origin` para não vazar referer ao MP.

### 23. Suporte a Apple Pay / Google Pay via MP
Mercado Pago Bricks já suporta. Reduz fricção no mobile em 30%+.

### 24. Adicionar campo `peso` no `Produto`
Hoje o Melhor Envio usa peso fixo 0.5kg. Em ecommerce de semijoias dá pra ter peso por SKU.

### 25. Exibir prazos estimados na página do produto
Tipo "Chega em 3-5 dias úteis em SP". Calculável via cookie de CEP do usuário.

### 26. Pixel + GA4 no servidor em vez do cliente (sGTM)
Você já tem CAPI para Meta. Vale fazer o mesmo para GA4 para resistir a adblockers.

### 27. Adicionar `X-Robots-Tag: noindex` no header HTTP para `/pagamento/`, `/finalizar/` e `/minha-conta/`
Já existe `noindex` na meta tag, mas se algum bot só olhar o header, ajuda.

### 28. Adicionar fallback de email quando Brevo cair
Se `BREVO_API_KEY` falhar, registrar o pedido na fila e tentar de novo (management command `enviar_emails_pendentes`).

### 29. Cache do home / categorias com `@cache_page(60)`
Catálogo muda pouco. 60s de cache aliviaria carga em pico de campanha.

### 30. Sentry / Bugsnag para monitorar exceptions em produção
Você captura tudo em logs, mas não há alerta. Sentry free tier resolve.

---

## 🎯 Plano de ação recomendado (ordem de execução)

| # | Item | Prioridade | Esforço | Reversível |
|---|------|------------|---------|------------|
| 1 | Reduzir payload do CallMeBot — mandar só "novo pedido #X" | 🔴 CRÍTICO | 5 min | sim |
| 2 | Rate-limit + cpf no `rastrear_pedido` | 🔴 CRÍTICO | 15 min | sim |
| 3 | Usar `validate_password()` em cadastro e checkout | 🔴 CRÍTICO | 10 min | sim |
| 4 | Mensagem genérica na falha de login no checkout (anti-enum) | 🟠 IMPORTANTE | 5 min | sim |
| 5 | `Disallow:` no `robots.txt` para rotas operacionais | 🟡 MELHORIA | 5 min | sim |
| 6 | Filtrar `visivel=True, estoque__gt=0` em `detalhe_produto_id` | 🟠 IMPORTANTE | 2 min | sim |
| 7 | Forçar `MERCADOPAGO_WEBHOOK_STRICT=True` quando `DEBUG=False` | 🟠 IMPORTANTE | 2 min | sim |
| 8 | Adicionar rate-limit em `pagamento_sucesso/pendente` | 🟠 IMPORTANTE | 5 min | sim |
| 9 | Peso/volume dinâmico no Melhor Envio (peso = items * 0.1) | 🟠 IMPORTANTE | 15 min | sim |
| 10 | Mascarar email nos logs (só `@dominio`) | 🟡 MELHORIA | 30 min | sim |
| 11 | `django-csp` em modo Report-Only | 🟠 IMPORTANTE | 30 min | sim |
| 12 | Cloudflare Turnstile em login/cadastro/cupom | 🟠 IMPORTANTE | 1h | sim |
| 13 | Paginação na home (Paginator 24) | 🟡 MELHORIA | 30 min | sim |
| 14 | `srcset` Cloudinary nas imagens | 🟡 MELHORIA | 1h | sim |
| 15 | django-otp / 2FA no admin | 🟡 MELHORIA | 1h | sim |
| 16 | Testes de `cpf_valido`, `assinatura_mp`, frete, cupom | 🟡 MELHORIA | 1-2h | sim |
| 17 | Extrair `base.html` (herança de template) | 🟡 MELHORIA | 3-4h | sim |
| 18 | Sentry para erros em produção | 🟢 OPCIONAL | 30 min | sim |

> Recomendado: aplicar os itens **1, 2, 3 primeiro** (1 hora de trabalho, fecha as 3 vulnerabilidades mais sérias e tudo é reversível). Itens **4-10** em uma segunda sessão. Depois ir descendo conforme tempo permitir.

---

## Pontos positivos a manter

Para registrar o que está **bem feito** (e não deve ser mexido):

- Token UUID por pedido em todas as rotas de pagamento/confirmação.
- Validação HMAC do webhook MP com timestamp e `compare_digest`.
- `select_for_update` + flag `estoque_baixado` impede dupla baixa.
- Flag `meta_purchase_sent` previne double-fire do Pixel/CAPI.
- Hash SHA256 dos PII no `meta_capi.py`.
- `dados_pagador_mercadopago` reconstrói payer só do banco — não confia no frontend.
- `payload_pagamento_seguro_para_log` oculta token e CPF.
- `BlockScannerPathsMiddleware` exclui o webhook MP corretamente.
- HSTS, cookies seguros, CSRF trusted origins, X-Frame-Options DENY.
- `SECURE_SSL_REDIRECT` + `SECURE_PROXY_SSL_HEADER` corretos para Railway.
- Rate-limit por IP em todas as rotas sensíveis com `django-ratelimit`.
- Cupom com `usado` incrementado via `F('usado') + 1` (race-safe).
- `detalhe_pedido` cliente exige ownership (`cliente=request.user`).
- Sequência de emails pós-compra com flags idempotentes por estágio.
- Sitemap XML + Schema.org Product/Breadcrumb/OnlineStore.

---

*Fim do relatório. Cada item desta auditoria foi pensado para ser aplicado isoladamente, sem dependência entre si.*
