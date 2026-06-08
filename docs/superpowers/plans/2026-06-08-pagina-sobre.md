# Página Sobre — Carta da Fundadora — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recriar a página `/sobre` como uma carta pessoal da fundadora Sabrina, com topo tipográfico, carta em fundo branco e assinatura inline no corpo do texto.

**Architecture:** Dois arquivos reescritos do zero — `sobre.html` (template Django) e `sobre.css` (estilos da página). O sistema de design existente (`base.css`) fornece todos os tokens (cores, fontes, espaçamentos) — o `sobre.css` só define os componentes exclusivos desta página. O texto da carta não é alterado.

**Tech Stack:** Django templates, CSS custom properties (tokens de `base.css`), `inline_static` tag para inlinar CSS no HTML.

---

### Task 1: Reescrever `sobre.css`

**Files:**
- Modify: `static/loja/css/pages/sobre.css`

- [ ] **Step 1: Substituir todo o conteúdo do arquivo pelo CSS abaixo**

```css
/* ==========================================================================
   BARRS STORE — SOBRE — CARTA DA FUNDADORA
   ========================================================================== */

.about-page {
  width: 100%;
  overflow-x: hidden;
  background: var(--color-bg);
}

/* ── TOPO TIPOGRÁFICO ────────────────────────────────────────────── */
.about-header {
  padding: clamp(2.5rem, 5vw, 4rem) clamp(1.25rem, 4vw, 2rem) clamp(2rem, 4vw, 3rem);
  text-align: center;
  background: var(--color-bg);
  border-bottom: 1px solid rgba(107, 122, 100, 0.14);
}

.about-header__line {
  width: 28px;
  height: 1px;
  background: var(--color-brand);
  margin: 0 auto var(--space-4);
  opacity: 0.45;
}

.about-header__eyebrow {
  display: block;
  font-family: var(--font-body);
  font-size: 0.5625rem;
  font-weight: 700;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--color-brand);
  margin-bottom: var(--space-4);
}

.about-header__title {
  font-family: var(--font-display);
  font-size: clamp(1.6rem, 3.2vw, 2.4rem);
  font-weight: 400;
  font-style: italic;
  color: var(--color-ink);
  line-height: 1.22;
  letter-spacing: -0.015em;
  margin-bottom: var(--space-3);
}

.about-header__sub {
  font-family: var(--font-body);
  font-size: 0.5625rem;
  color: var(--color-ink-muted);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  font-weight: 600;
}

/* ── SEÇÃO DA CARTA ──────────────────────────────────────────────── */
.about-letter {
  padding: clamp(2rem, 4vw, 3rem) clamp(1.25rem, 4vw, 2rem) clamp(2.5rem, 5vw, 4rem);
}

.about-letter__card {
  background: var(--color-surface);
  border-radius: 2px;
  padding: clamp(1.75rem, 4vw, 2.75rem) clamp(1.5rem, 4vw, 2.5rem);
  box-shadow:
    0 2px 12px rgba(0, 0, 0, 0.04),
    0 1px 3px rgba(0, 0, 0, 0.06);
  max-width: 640px;
  margin: 0 auto;
}

/* Cabeçalho interno da carta */
.about-letter__head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  margin-bottom: var(--space-6);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--color-border-soft);
}

.about-letter__from {
  font-family: var(--font-body);
  font-size: 0.5rem;
  font-weight: 700;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--color-brand);
}

.about-letter__date {
  font-family: var(--font-body);
  font-size: 0.5rem;
  color: var(--color-ink-muted);
  letter-spacing: 0.12em;
}

/* Corpo da carta */
.about-letter__body p {
  font-family: var(--font-display);
  font-size: clamp(0.9rem, 1.6vw, 1.0125rem);
  line-height: 1.92;
  color: var(--color-ink-soft);
  font-weight: 400;
  margin-bottom: var(--space-5);
}

/* Fechamento inline ("Com carinho, / Sabrina, / Fundadora") */
.about-letter__closing {
  font-family: var(--font-display);
  font-size: clamp(0.9rem, 1.6vw, 1.0125rem);
  line-height: 1.92;
  color: var(--color-ink-soft);
  font-style: italic;
  margin-top: var(--space-6);
}

/* ── RESPONSIVIDADE ──────────────────────────────────────────────── */
@media (max-width: 600px) {
  .about-letter__card {
    padding: 1.5rem 1.25rem;
  }
  .about-header__title {
    font-size: 1.5rem;
  }
}
```

- [ ] **Step 2: Verificar que o arquivo foi salvo corretamente**

```bash
head -5 static/loja/css/pages/sobre.css
```
Esperado: primeira linha é `/* ==========================================================================`

---

### Task 2: Reescrever `sobre.html`

**Files:**
- Modify: `loja/templates/sobre.html`

- [ ] **Step 1: Substituir todo o conteúdo do template pelo HTML abaixo**

```django
{% extends "base.html" %}
{% load static inline_static %}

{% block title %}Sobre — Barrs Store{% endblock %}

{% block page_css %}<style>
{% inline_static 'loja/css/pages/sobre.css' %}
</style>{% endblock %}

{% block content %}
<nav class="nav">
  <a href="{% url 'home' %}" class="nav__logo">
    <img src="https://res.cloudinary.com/dsw5fkmwp/image/upload/q_auto/f_auto/v1777401449/ChatGPT_Image_28_de_abr._de_2026_15_37_19_ovzkth.png" alt="Barrs Store" width="40" height="40" decoding="async">
    Barrs Store
  </a>
  <ul class="nav__links">
    <li><a href="{% url 'home' %}">Início</a></li>
    <li><a href="{% url 'home' %}#produtos">Coleção</a></li>
    <li><a href="{% url 'sobre' %}" class="active">Sobre</a></li>
    <li><a href="{% url 'contato' %}">Contato</a></li>
  </ul>
  <div class="nav__right">
    {% if user.is_authenticated %}
      <a href="{% url 'minha_conta' %}" class="nav__icon-btn" aria-label="Minha conta">
        <svg class="icon icon--16" aria-hidden="true"><use href="#i-user"/></svg>
      </a>
    {% else %}
      <a href="{% url 'login' %}" class="nav__icon-btn">Entrar</a>
    {% endif %}
    <a href="{% url 'carrinho' %}" class="nav__icon-btn" aria-label="Carrinho">
      <svg class="icon icon--16" aria-hidden="true"><use href="#i-cart"/></svg>
      Carrinho
      {% if qtd_carrinho > 0 %}<span class="badge-count">{{ qtd_carrinho }}</span>{% endif %}
    </a>
  </div>
</nav>
{% include "partials/category_nav.html" %}

<main class="about-page" id="conteudo-principal">

  <header class="about-header" data-reveal>
    <div class="about-header__line"></div>
    <span class="about-header__eyebrow">Uma mensagem da fundadora</span>
    <h1 class="about-header__title">A Barrs nasceu de uma<br><em>decisão que mudou tudo</em></h1>
    <p class="about-header__sub">Sabrina &middot; Fundadora &middot; 2026</p>
  </header>

  <section class="about-letter" aria-label="Carta da fundadora">
    <div class="about-letter__card" data-reveal="rise">

      <div class="about-letter__head">
        <span class="about-letter__from">De: Sabrina, fundadora</span>
        <span class="about-letter__date">Barrs Store &middot; 2026</span>
      </div>

      <div class="about-letter__body">
        <p>A Barrs nasceu de uma decisão que mudou tudo.</p>
        <p>Meu nome é Sabrina. Em 2026, aos 29 anos, tomei uma das decisões mais difíceis da minha vida. Depois de trabalhar por quase oito anos na mesma empresa, conquistar estabilidade, crescer profissionalmente e ocupar um cargo importante, percebi que existia um sonho que continuava falando mais alto dentro de mim: o sonho de construir algo meu.</p>
        <p>Sempre gostei de acessórios. Sempre acreditei que uma peça tem o poder de transformar a forma como nos sentimos. Não porque ela muda quem somos, mas porque ela nos lembra da nossa própria beleza, da nossa confiança e da nossa essência.</p>
        <p>Por muito tempo, esse sonho ficou guardado. E não foi por falta de vontade. Foi por medo. Medo de abrir mão da estabilidade que eu havia construído durante anos. Medo de deixar para trás um cargo que conquistei com muito esforço. Medo de abandonar a segurança financeira para começar algo do zero. Eu sabia exatamente o que estava deixando para trás, mas não sabia o que encontraria pela frente. E talvez essa tenha sido a parte mais difícil.</p>
        <p>Durante muito tempo, tentei ignorar essa vontade de empreender. Mas chegou um momento em que percebi que o medo de nunca tentar era maior do que o medo de arriscar. Eu sentia que precisava de algo a mais. Precisava me desafiar. Precisava construir algo que carregasse meus valores, minha dedicação e minha identidade.</p>
        <p>Queria ter a oportunidade de olhar para trás no futuro e saber que pelo menos tentei viver o sonho que sempre esteve dentro de mim. Foi então que decidi deixar para trás a segurança que conhecia para viver algo completamente novo. Nascia ali a Barrs Store.</p>
        <p>A Barrs nunca foi apenas sobre acessórios. Ela nasceu da coragem de recomeçar. Nasceu de noites de planejamento, pesquisas, aprendizados, erros, acertos e da vontade de construir uma marca que entregasse muito mais do que produtos. Queria criar uma experiência. Queria que cada cliente recebesse não apenas uma peça bonita, mas sentisse o carinho colocado em cada detalhe. Da escolha dos produtos à embalagem. Da compra à entrega. Da primeira visita ao site até o momento em que a caixa é aberta.</p>
        <p>Foi dessa certeza que nasceu a essência da Barrs. Os detalhes mudam tudo. Uma peça escolhida com carinho pode transformar um look. Uma embalagem preparada com cuidado pode transformar uma entrega. Um pequeno gesto pode transformar um dia comum. E são esses detalhes que buscamos entregar todos os dias.</p>
        <p>A Barrs nasceu de um sonho. Mas hoje ela é construída por cada pessoa que escolhe fazer parte dessa história. Se você está aqui, saiba que sua presença significa muito para nós.</p>
        <p>Cada pedido, cada mensagem e cada cliente que confia no nosso trabalho nos lembra diariamente porque essa decisão valeu a pena.</p>
        <p>Obrigada por apoiar uma marca que nasceu da coragem de acreditar.</p>
      </div>

      <p class="about-letter__closing">
        Com carinho,<br>
        Sabrina,<br>
        Fundadora da Barrs Store.
      </p>

    </div>
  </section>

</main>

{% include "partials/footer.html" %}

<a href="https://wa.me/5511913225256?text=Olá!%20Vim%20pelo%20site%20da%20Barrs%20Store!" class="wa-float" target="_blank" rel="noopener" aria-label="WhatsApp">
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
  </svg>
</a>

{% endblock %}
```

- [ ] **Step 2: Verificar que o template foi salvo**

```bash
head -3 loja/templates/sobre.html
```
Esperado:
```
{% extends "base.html" %}
{% load static inline_static %}
```

---

### Task 3: Commitar e verificar

**Files:** nenhum arquivo novo

- [ ] **Step 1: Rodar collectstatic para processar o CSS**

```bash
python manage.py collectstatic --no-input 2>&1 | tail -5
```
Esperado: `X static files copied` ou `X static files post-processed` sem erros.

- [ ] **Step 2: Commitar as alterações**

```bash
git add loja/templates/sobre.html static/loja/css/pages/sobre.css
git commit -m "feat: recriar página sobre como carta da fundadora"
```

- [ ] **Step 3: Abrir a página no navegador e verificar visualmente**

Navegar para `/sobre/` e confirmar:
- Topo tipográfico com eyebrow "UMA MENSAGEM DA FUNDADORA" e título em itálico
- Carta em card branco com cabeçalho "De: Sabrina, fundadora / Barrs Store · 2026"
- Todos os parágrafos do texto presentes
- Fechamento "Com carinho, / Sabrina, / Fundadora da Barrs Store." em itálico no final do card
- Nenhuma seção de pilares, embalagem ou CTA após a carta
- Footer existente aparece logo abaixo do card
- WhatsApp float button presente
