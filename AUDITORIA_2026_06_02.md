# 🔍 Relatório de Auditoria — BarrsStore
**Data:** 2026-06-02
**Versão analisada:** branch `main` (HEAD `039d618`)
**Stack:** Django 6.0.4 · SQLite/Postgres · Cloudinary · Mercado Pago · Brevo · Melhor Envio · Redis · WhatsApp Evolution

---

## Resumo Executivo

O projeto está em **bom estado geral de maturidade**. Configurações de segurança no `settings.py` são sólidas (CSP com nonce, HSTS, cookies HttpOnly+Secure, `SECRET_KEY` via env, webhook MP com HMAC, rate-limit dedicado, Turnstile preparado, 2FA via `django_otp`). Há cobertura de testes razoável (idempotência de baixa de estoque, validação CPF, autorização cross-cart, assinatura MP) — algo incomum em projetos desse porte.

Os achados **críticos** se concentram em **3 pontos**: vazamento de stack-trace via `JsonResponse({'erro': str(e)})` no cálculo de frete, registro de email **case-sensitive** que permite cadastrar `User@x.com` e `user@x.com` como contas separadas, e a falta de validação no parâmetro `?mes=` do dashboard. Os demais achados são polimentos sobre uma base já robusta.

**Total de problemas encontrados:**
| Classificação | Quantidade |
|---|---|
| 🔴 Crítico | 4 |
| 🟡 Médio | 9 |
| 🟢 Leve | 7 |
| 💡 Sugestão | 6 |

---

## 🔴 CRÍTICOS (resolver imediatamente)
> Problemas que podem causar perda de dados, invasão, ou quebra do sistema em produção.

### C-01 — Exposição de stack-trace e detalhes internos via `str(e)` no cálculo de frete
**Arquivo:** `loja/views/shipping.py` (linha 321-322)
**Descrição:** O `except Exception as e: return JsonResponse({'erro': str(e)}, status=500)` envia a mensagem da exceção ao cliente. Em produção isso pode vazar caminhos de arquivo (`KeyError: 'MELHOR_ENVIO_TOKEN'`), credenciais parciais (token de Bearer truncado em traceback de `requests`), ou erros do banco — todos úteis para um atacante.
**Impacto:** Reconhecimento facilitado (info-disclosure / OWASP A05). Ferramentas como `nuclei`/`ffuf` colecionam essas mensagens automaticamente.
**Como corrigir:**
```python
# loja/views/shipping.py:321-322 — ANTES
    except Exception as e:
        return JsonResponse({'erro': str(e)}, status=500)

# DEPOIS
    except Exception:
        logger.exception('[ME] Falha ao calcular frete cep=%s', cep_destino)
        return JsonResponse({'erro': 'Não foi possível calcular o frete agora.'}, status=500)
```

---

### C-02 — Cadastro permite duplicar conta com e-mail em caixas diferentes (case-sensitive)
**Arquivo:** `loja/views/account.py` (linha 45), `loja/views/cart.py` (linha 139)
**Descrição:** `User.objects.filter(email=email).exists()` é case-sensitive em Postgres. Um usuário cadastrado com `Bibico@gmail.com` e outro com `bibico@gmail.com` viram duas contas distintas — quem chegar pelo checkout (`account.py:45`) escapa do guard porque a comparação é exata. Como o `username` é gravado tal-qual o e-mail digitado, isso bagunça `authenticate()` se a pessoa não usar a caixa exata do cadastro. O `cart.py:139` faz a busca com `__iexact` — então as duas regras divergem.
**Impacto:** Contas-fantasma (mesmo cliente humano com 2 perfis = histórico de pedido fragmentado, cupom de fidelidade aplicado duas vezes), risco de account takeover muito barato em casos de domínios com aliasing.
**Como corrigir:**
```python
# loja/views/account.py — cadastro()
# ANTES
email = request.POST.get('email', '').strip()
...
elif User.objects.filter(email=email).exists():

# DEPOIS — normalize antes de persistir e use __iexact
email = request.POST.get('email', '').strip().lower()
...
elif User.objects.filter(email__iexact=email).exists():
```
Aplique o mesmo `.lower()` ao gravar `username=email` em todo o projeto (account.py cadastro/login, cart.py `_resolver_cliente`). Considere adicionar uma migration de data + constraint `LOWER(email) UNIQUE` para travar isso no banco.

---

### C-03 — `dashboard_saude` aceita `?mes=` sem limitar range e crasha com valores extremos
**Arquivo:** `loja/views/dashboard.py` (linhas 29-36)
**Descrição:** O `int(...)` valida o formato mas não o range — `?mes=9999-13` cai num `ValueError` que está coberto, mas `?mes=99999-12` passa e gera `OverflowError` no `replace(year=99999)`, que **não** está no `except`. Mais sutil: como o dashboard só é acessível por staff, isso não vira RCE, mas pode ser usado para forçar 500s repetidos no painel (DoS leve do admin).
**Impacto:** Indisponibilidade pontual do painel de saúde. Em logs, o stack-trace vaza estrutura de tabelas.
**Como corrigir:**
```python
# loja/views/dashboard.py:29-41 — ANTES
mes_param = request.GET.get('mes', '') or hoje.strftime('%Y-%m')
try:
    ano_sel, mes_sel = map(int, mes_param.split('-'))
    inicio_mes_sel = inicio_dia.replace(year=ano_sel, month=mes_sel, day=1)
    ...
except (ValueError, TypeError):
    ...

# DEPOIS — valida ano/mes em ranges sãos
mes_param = request.GET.get('mes', '') or hoje.strftime('%Y-%m')
try:
    ano_sel, mes_sel = map(int, mes_param.split('-'))
    if not (2020 <= ano_sel <= hoje.year + 1) or not (1 <= mes_sel <= 12):
        raise ValueError
    inicio_mes_sel = inicio_dia.replace(year=ano_sel, month=mes_sel, day=1)
    ...
except (ValueError, TypeError, OverflowError):
    ...
```

---

### C-04 — Webhook Mercado Pago: assinatura **avisada** mas não bloqueada em DEBUG, e em prod aceita request sem secret se ausente
**Arquivo:** `loja/views/payment.py` (linhas 781-786), `loja/mercadopago_security.py` (linhas 36-44)
**Descrição:** Em produção, se `MERCADOPAGO_WEBHOOK_SECRET` estiver vazio (ex: alguém remove a env por engano), `validar_assinatura_mercadopago` retorna `True, 'sem_secret_modo_compatibilidade'`. A view só rejeita se `MERCADOPAGO_WEBHOOK_STRICT=True`, mas o `MP_WEBHOOK_STRICT` no `settings.py:323` **é forçado True quando não-DEBUG**, então isso *está* coberto. Porém, há uma janela em deploys onde `DEBUG=True` momentaneamente (debug-toolbar / Railway preview) e qualquer um pode forjar `POST /pagamento/webhook/` com `data.id` apontando para o próprio pedido pendente — confirmando-o sem pagamento real.
**Impacto:** Em ambientes de staging/preview com DEBUG ligado, um atacante consegue marcar pedido como `confirmado` e disparar `criar_envio_melhor_envio()` — etiqueta real é gerada e estoque é baixado.
**Como corrigir:**
- Force a verificação de assinatura **mesmo em DEBUG** para webhooks de pagamento — não há razão legítima de aceitar webhook sem secret em qualquer ambiente.
- Adicione uma allowlist de IPs do MP como segunda camada (eles publicam o range).
```python
# loja/mercadopago_security.py — modo estrito SEMPRE para webhook
def validar_assinatura_mercadopago(request, data):
    secret = getattr(settings, 'MERCADOPAGO_WEBHOOK_SECRET', '')
    if not secret:
        logger.error('MERCADOPAGO_WEBHOOK_SECRET ausente. Webhook recusado.')
        return False, 'secret_ausente'
    ...
```
E remova a flag `MERCADOPAGO_WEBHOOK_STRICT` — webhook de pagamento **nunca** deve ser não-estrito.

---

## 🟡 MÉDIOS (resolver em breve)
> Problemas que degradam segurança, manutenibilidade ou experiência do usuário.

### M-01 — `criar_preferencia`: sem CSRF + sem `@login_required` permite gerar preferências MP em pedidos de terceiros
**Arquivo:** `loja/views/payment.py` (linha 463-465)
**Descrição:** A view é protegida pelo `access_token` UUID do pedido (`get_pedido_por_token`), o que é razoável. Porém, ela não usa `@csrf_exempt` — boa — mas também não verifica que o pedido **pertence ao request.user** quando o usuário está logado. Se o `access_token` vazar (e ele aparece em URL, e-mail, log de proxy reverso, screenshot do cliente compartilhado em suporte), qualquer um com o link pode criar preferência. A URL do pedido é compartilhada em `enviar_email_confirmacao` e em `enviar_whatsapp_pedido`.
**Como corrigir:** Adicione verificação opcional: se `request.user.is_authenticated` E `pedido.cliente_id` foi setado, exija `pedido.cliente_id == request.user.id`. Mantém UX para guest checkout via token.

### M-02 — `aplicar_cupom_ajax`: enumera cupons sem rate-limit por cupom
**Arquivo:** `loja/views/cart.py` (linha 492-524)
**Descrição:** O rate-limit é `20/m` por IP, mas o endpoint responde com mensagens diferentes para "cupom não encontrado" (404) vs "cupom esgotado" (400). Um atacante pode enumerar a base de cupons (`BSOFF10`, `BLACKFRIDAY`, `BARRS25`...) em até 20 tentativas/minuto. Em mãos amigas vira distribuição não-autorizada de descontos.
**Como corrigir:**
- Unifique a resposta: sempre `{ok: False, erro: 'Cupom inválido.'}` para "não encontrado" e "esgotado".
- Diminua o rate-limit para 5/m por IP e adicione `key='user_or_ip'` para barrar via sessão também.

### M-03 — `processar_pagamento_brick` aceita `installments` e `issuer_id` do front sem teto
**Arquivo:** `loja/views/payment.py` (linhas 590-601)
**Descrição:** Os campos vêm do form do Brick (que é controlado pelo MP), mas tecnicamente o body é JSON livre — um cliente pode injetar `installments: 999`. O MP rejeitará, mas a tentativa é gravada no log com o payload e pode poluir.
**Como corrigir:** Clamp `installments` em `1 <= n <= 12`. Aceite `issuer_id` só como int.

### M-04 — Logs detalhados de payload MP gravam `external_reference` (= ID do pedido) misturado a `payment_method_id` — facilita correlação para um atacante com acesso a logs
**Arquivo:** `loja/views/payment.py` (linhas 607-617)
**Descrição:** `payload_pagamento_seguro_para_log` já mascara o que importa (token, CPF, e-mail). Mas o log inclui `external_reference` (= ID sequencial do pedido) + `payment_method_id` em `INFO`, o que permite a um insider mapear método de pagamento por cliente. Não é vazamento de PII direto, mas em LGPD entra como dado pessoal indireto.
**Como corrigir:** Marque esses logs como `DEBUG` em produção (e mantenha `INFO` só para o ID do pedido e status final).

### M-05 — `Pedido.access_token` aparece **no admin** como readonly mas é renderizado em plain text
**Arquivo:** `loja/admin.py` (linha 75, 115)
**Descrição:** O `access_token` é a chave que dá acesso ao pedido sem login. Mostrá-lo no admin (que tem 2FA e está atrás de `painel/`) é tolerável, mas qualquer staff com sessão admin comprometida (XSS via outra rota, screenshot em ticket de suporte com a aba do admin aberta) pode replayar o pedido para confirmação fraudulenta de pagamento via `pagamento_sucesso` se houver `payment_id` válido.
**Como corrigir:** Não exiba o `access_token` no fieldset visível. Se precisar para suporte, exponha um botão "Gerar novo link de acompanhamento" que copia para clipboard.

### M-06 — `dados_pagador_mercadopago` faz fallback para e-mail global se `pedido.email` estiver vazio
**Arquivo:** `loja/views/payment.py` (linha 176)
**Descrição:** `pedido.email or os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com')` — usa o e-mail da loja como pagador se o pedido não tiver e-mail. Isso é uma anomalia: todo pedido **deveria** ter e-mail (o checkout valida). Se o fallback dispara, é bug em outro lugar e mascara o defeito.
**Como corrigir:** Levantar exceção ou retornar erro 400 se `pedido.email` estiver vazio em fluxo de pagamento. Não fazer fallback silencioso.

### M-07 — `meta_pixel.html` tem o Pixel ID **hardcoded**, mas o `META_PIXEL_ID` da env existe e não é usado
**Arquivo:** `loja/templates/partials/meta_pixel.html` (linha 16, 27), `barrs_store/settings.py` (linha 50)
**Descrição:** O ID `1413794504078637` está chumbado no template. `settings.META_PIXEL_ID` existe, mas só é usado no CAPI server-side. Trocar de pixel exige deploy do template em vez de alterar env.
**Como corrigir:**
```django
fbq('init','{{ meta_pixel_id|default:"1413794504078637" }}');
```
E inclua `meta_pixel_id` no `context_processors.marketing_tags`.

### M-08 — `static/loja/css/base.css` é injetado inline a cada request, perdendo cache do browser
**Arquivo:** `loja/templates/base.html` (linhas 20-22), `loja/templatetags/inline_static.py`
**Descrição:** O `inline_static` lê o CSS via `lru_cache(64)` e injeta dentro de `<style>` no HTML. **Vantagem**: zero round-trip, ótimo para FCP. **Desvantagem**: o cliente baixa o CSS embedded a cada navegação — em um catálogo de 6 páginas isso é ~6× o peso do CSS sem reaproveitamento. Para a home + detalhe + carrinho juntos isso fica em torno de 200-300 KB extras por sessão.
**Como corrigir:** Mantenha o inline para o CSS **above-the-fold** (hero, nav, layout-shell). Mande o resto como `<link>` com `WHITENOISE_MAX_AGE=31536000` (já configurado) — assim a partir da 2ª navegação o browser usa cache.

### M-09 — `enviar_email_abandono_1` itera `carrinho.itens` mas usa `<img>` Cloudinary com URL crua sem dimensões reduzidas
**Arquivo:** `loja/views/emails.py` (linha 581-582)
**Descrição:** `item.produto.imagem.url` no e-mail manda a URL original do Cloudinary (potencialmente 2MB+ por imagem). Em Outlook/Apple Mail isso quebra Lighthouse de cliente e pode atrasar o render do e-mail.
**Como corrigir:** Use uma transformação Cloudinary inline: `c_fill,w_96,h_96,q_auto,f_auto` na URL antes de embutir.

---

## 🟢 LEVES (resolver quando possível)
> Melhorias de qualidade, legibilidade e boas práticas.

### L-01 — Função `calcular_frete_melhor_envio` ultrapassa 100 linhas e mistura validação, montagem de payload, parsing de resposta e filtragem
**Arquivo:** `loja/views/shipping.py` (linhas 204-322)
**Descrição:** Refator: extrair `_montar_payload_cotacao(carrinho, cep)`, `_filtrar_opcoes_permitidas(data)`. Facilita teste.

### L-02 — `loja/views/__init__.py` faz `from .x import *` — quebra IDE/autocompletar e estoura no PyLint
**Arquivo:** `loja/views/__init__.py`
**Descrição:** O uso é justificado para compatibilidade com `views.<nome>` no urls.py, mas dificulta descobrir qual módulo expõe qual nome. Alternativa: listar `__all__` em cada submódulo e importar nominalmente no `__init__`.

### L-03 — `enviar_email_*` aceita uma `Exception` genérica e perde o tipo
**Arquivo:** `loja/views/emails.py` (linhas 353, 383, 423, 522 etc.)
**Descrição:** O padrão `except Exception as exc: logger.exception(...)` é OK como rede de segurança, mas mascara erros de programação (TypeError em template, AttributeError) como falha de envio. Considere capturar especificamente `requests.RequestException` + `KeyError` no payload Brevo.

### L-04 — `home()` constrói `categoria_aliases` toda request — dict literal de 12 chaves
**Arquivo:** `loja/views/store.py` (linhas 45-59)
**Descrição:** Mova para constante de módulo (`_CATEGORIA_ALIASES = {...}`). Microoptimização, mas reduz alocações em hot path.

### L-05 — `models.Produto.save()` faz query `Produto.objects.filter(slug=slug).exclude(pk=self.pk).exists()` em loop sem índice em `slug` além do `unique=True`
**Arquivo:** `loja/models.py` (linhas 92-95)
**Descrição:** `unique=True` cria índice, então o `.exists()` é rápido. Mas em race-condition (dois admins salvando "Anel X" simultâneo), pode falhar com IntegrityError. Acrescente `try/except IntegrityError → retry com contador+1`.

### L-06 — `requirements.txt` mistura versões pinned mas algumas dependências transitivas estão soltas
**Arquivo:** `requirements.txt`
**Descrição:** `PyMySQL==1.1.2` está presente mas o projeto usa `psycopg2-binary`. Se não tem MySQL, remova — reduz superfície de CVE.

### L-07 — `meta_pixel.html`: `<img>` do noscript não tem `alt` e `style` inline
**Arquivo:** `loja/templates/partials/meta_pixel.html` (linha 26-28)
**Descrição:** A11y: adicionar `alt=""` explícito. Pixel já está dentro do CSP via `connect-src facebook.com`. Sem impacto funcional.

---

## 💡 SUGESTÕES DE IMPLEMENTAÇÃO
> Funcionalidades ou melhorias que valem a pena adicionar.

### S-01 — Ativar 2FA obrigatório no admin (`django-otp` já instalado)
**Por quê implementar:** O projeto já tem `django_otp` no `INSTALLED_APPS` e `OTPMiddleware`, mas o gate não está ativo — qualquer staff com senha entra direto. Como há transações financeiras e dados PII (CPF, endereço), 2FA admin é norma do mercado (Stripe, Magalu, Nubank).
**Complexidade:** Baixa — basta adicionar `decorator_from_middleware(OTPRequiredMiddleware)` no admin ou usar `django-otp` AdminSite override.
**Referência:** https://django-otp-official.readthedocs.io/en/stable/

### S-02 — Mover `db.sqlite3` para fora do repositório (já está no `.gitignore`, mas o arquivo segue no diretório)
**Por quê implementar:** O `db.sqlite3` no working tree tem 573KB e contém dados reais de produção (pedidos, e-mails, telefones). Se o repo for clonado em outra máquina ou virar bundle de bug report, esses dados vazam. Mover para `~/.local/share/barrs/db.sqlite3` ou `data/db.sqlite3` (gitignored).
**Complexidade:** Baixa.

### S-03 — Adicionar testes de regressão de UI (visual diff) para mobile
**Por quê implementar:** O projeto tem testes Django sólidos para lógica, mas zero testes visuais. Como já existe instrução de não mexer no layout (memória do usuário), adicionar Playwright com screenshot diff em viewports 375/768/1280 evita regressão acidental.
**Complexidade:** Média.

### S-04 — Cache de `get_carrinho_info` por sessão
**Por quê implementar:** Toda página chama `get_carrinho_info(request)` no context, que dispara 1 query `Carrinho.objects.get(id=carrinho_id)` + 1 query agregada por item. Em uma navegação de 5 páginas, são 10+ queries só para o badge. Cachear o `qtd_carrinho` na sessão (invalidando em `adicionar_carrinho`, `remover_item`, `deletar_item`) reduz o overhead.
**Complexidade:** Baixa.

### S-05 — Sentry release tracking + source-maps
**Por quê implementar:** Sentry SDK já está configurado, mas sem release tag (`sentry_sdk.init(release=...)`). Sem isso, regressões aparecem como "novo erro" toda hora e não dá pra fazer regression-detection. Adicione `release=os.environ.get('RAILWAY_GIT_COMMIT_SHA', 'dev')`.
**Complexidade:** Baixa.

### S-06 — Implementar `DataDog`/`pytest-django` coverage CI
**Por quê implementar:** Existem ~25 testes em `tests.py` mas eles vivem num único arquivo de 521 linhas. Quebrar em `tests/test_<feature>.py` + adicionar `coverage` no Railway pipeline + falhar PR se `< 60%`. Hoje não há como saber o que está coberto.
**Complexidade:** Média.

---

## 📋 Checklist de Ações

### Críticos
- [ ] **C-01**: Trocar `JsonResponse({'erro': str(e)})` por mensagem genérica em `shipping.py:321`
- [ ] **C-02**: Normalizar e-mail (lower) + `__iexact` em `account.py:45` e `cart.py:139` + migration de data
- [ ] **C-03**: Validar range de `ano/mes` em `dashboard.py:31` e capturar `OverflowError`
- [ ] **C-04**: Tornar verificação de assinatura MP **sempre estrita** (remover modo compatibilidade)

### Médios
- [ ] **M-01**: Adicionar guard `pedido.cliente_id == request.user.id` em `criar_preferencia`
- [ ] **M-02**: Unificar mensagem de erro em `aplicar_cupom_ajax` (não distinguir 404 vs 400)
- [ ] **M-03**: Validar `installments` em `[1, 12]` no `processar_pagamento_brick`
- [ ] **M-04**: Mover logs `[MP-BRICK] Payload seguro` de `INFO` para `DEBUG`
- [ ] **M-05**: Esconder `access_token` do fieldset do admin
- [ ] **M-06**: Falhar em vez de fallback no e-mail vazio em `dados_pagador_mercadopago`
- [ ] **M-07**: Mover Pixel ID hardcoded para `settings.META_PIXEL_ID` via context_processor
- [ ] **M-08**: Inline só CSS critical, resto via `<link>` cacheado
- [ ] **M-09**: Reduzir imagens no e-mail de abandono via transformação Cloudinary

### Leves
- [ ] **L-01**: Quebrar `calcular_frete_melhor_envio` em helpers
- [ ] **L-02**: Substituir `from .x import *` por `__all__` explícito
- [ ] **L-03**: Capturar exceções específicas em `enviar_email_*`
- [ ] **L-04**: Extrair `_CATEGORIA_ALIASES` para constante de módulo
- [ ] **L-05**: Retry em `IntegrityError` no `Produto.save()`
- [ ] **L-06**: Remover `PyMySQL` do `requirements.txt` se não-usado
- [ ] **L-07**: Adicionar `alt=""` no `<img>` noscript do Pixel

### Sugestões
- [ ] **S-01**: Ativar 2FA admin obrigatório
- [ ] **S-02**: Mover `db.sqlite3` para fora do repo
- [ ] **S-03**: Adicionar testes visuais (Playwright)
- [ ] **S-04**: Cachear `qtd_carrinho` na sessão
- [ ] **S-05**: `release` no `sentry_sdk.init`
- [ ] **S-06**: Quebrar `tests.py` + coverage no CI

---

## Pontos fortes do projeto (manter)

Para não passar a impressão de que está tudo errado — coisas que **já estão certas** e devem ser preservadas:

- ✅ **`SECRET_KEY` exige env em prod** (`settings.py:17-21`) — bem feito.
- ✅ **CSP com nonce por request** (`middleware.py:101-125`) — referencial.
- ✅ **`SECURE_HSTS_SECONDS=31536000` + preload** em prod.
- ✅ **Webhook MP com HMAC + tolerância de timestamp** (`mercadopago_security.py`).
- ✅ **Idempotência** em `baixar_estoque_pedido`, `enviar_meta_purchase_pedido`, dedupe no webhook por `x-request-id`.
- ✅ **`select_for_update()`** em `confirmar_pedido_pago` e `baixar_estoque_pedido` — protege contra double-spend.
- ✅ **`select_related('produto')`** consistente em todos os loops de itens.
- ✅ **Índices** em `Produto`, `Pedido`, `EmailPendente`, `Lead`.
- ✅ **`url_has_allowed_host_and_scheme`** no `?next=` do login e do add-to-cart — bloqueia open redirect.
- ✅ **Rate-limit** em endpoints sensíveis (`@ratelimit` + `AdminRateLimitMiddleware`).
- ✅ **CSRF habilitado em todas as views** (apenas o webhook MP usa `@csrf_exempt`, como tem que ser).
- ✅ **`payload_pagamento_seguro_para_log`** mascara CPF/token/e-mail.
- ✅ **Cobertura de teste** em pontos críticos (idempotência, autorização cross-cart, assinatura MP, CPF, cupom, frete).
- ✅ **`escapejs` no `data-pixel-name`** nos cards de produto.
- ✅ **`unique_together=('carrinho','produto','tamanho')`** previne carrinho com itens duplicados.

---

*Auditoria gerada em 2026-06-02 sobre o commit `039d618` (main).*
