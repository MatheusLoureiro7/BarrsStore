# Design: Página Sobre — Barrs Store

**Data:** 2026-06-08
**Status:** Aprovado

---

## Objetivo

Recriar a página `/sobre` para apresentar a história pessoal da fundadora Sabrina de forma íntima e autêntica, no formato de carta. O texto não deve ser alterado — apenas o layout e o design são recriados do zero.

---

## Decisões de Design

| Dimensão | Decisão | Razão |
|---|---|---|
| Estrutura geral | Carta/Founder's Note | Formato mais honesto para um texto pessoal e emocional |
| Topo da página | Tipográfico — sem foto | Toda a atenção vai para as palavras; mais intimista |
| Após a carta | Nada — a página termina | Máximo impacto, zero distração |
| Assinatura | Inline no corpo da carta | "Com carinho, / Sabrina, / Fundadora da Barrs Store." como parte do texto, em itálico |
| Fechamento externo | Removido | Elimina redundância |

---

## Estrutura da Página

```
Nav (existente)
└── Page Header (tipográfico)
    ├── Linha decorativa horizontal
    ├── Eyebrow: "Uma mensagem da fundadora"
    ├── H1: "A Barrs nasceu de uma decisão que mudou tudo"
    └── Sub: "Sabrina · Fundadora · 2026"

└── Letter Section
    └── Letter Card (fundo branco, sombra suave)
        ├── Letter Head
        │   ├── "De: Sabrina, fundadora"
        │   └── "Barrs Store · 2026"
        ├── Letter Body (texto completo, parágrafos)
        └── Letter Closing (itálico, inline)
            "Com carinho,
            Sabrina,
            Fundadora da Barrs Store."

Footer (existente)
```

---

## Tipografia

- **Corpo da carta:** Georgia serif, 15px, line-height 1.92, cor `#3a3a3a`
- **Fechamento/assinatura:** Georgia serif, itálico, mesma fonte do corpo
- **Eyebrow do topo:** Montserrat, 9px, letter-spacing 0.32em, maiúsculas, cor `var(--color-brand)`
- **H1 do topo:** Playfair Display, 28px–34px (clamp), itálico, peso 400
- **Letter head:** Montserrat, 8px, letra maiúscula, `var(--color-brand)`

---

## Cores e Tokens

Usa integralmente o sistema de design existente em `base.css`:
- `--color-bg: #F5F6EE` — fundo da página
- `--color-surface: #FFFFFF` — card da carta
- `--color-brand: #6B7A64` — verde sálvia (eyebrows, linha decorativa)
- `--color-ink: #1A1A1A` — títulos
- `--color-ink-soft: #333333` / `#3a3a3a` — corpo da carta
- `--font-display: Playfair Display` — títulos
- `--font-body: Montserrat` — labels, eyebrows

---

## Arquivos a Modificar

| Arquivo | Ação |
|---|---|
| `loja/templates/sobre.html` | Recriar completamente |
| `static/loja/css/pages/sobre.css` | Recriar completamente |

---

## Texto (não alterar)

O texto completo está no briefing original. Começa em "A Barrs nasceu de uma decisão que mudou tudo." e termina com o bloco de assinatura "Com carinho, / Sabrina, / Fundadora da Barrs Store." — que deve aparecer no final do corpo da carta, em itálico, como parágrafo de fechamento.

---

## O que NÃO entra nesta versão

- Hero com foto
- Seção de pilares (Banhos Premium, Garantia, Entrega)
- Seção de embalagem premium
- Botão CTA após a carta
- Bloco de assinatura separado / estilizado fora do corpo
- Fechamento "com carinho, Barrs Store" externo à carta
