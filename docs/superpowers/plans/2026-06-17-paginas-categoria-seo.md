# Páginas de Categoria com URL Própria (SEO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Política de git deste projeto:** NÃO rodar `git add`/`git commit`/`git push` automaticamente em nenhum passo deste plano, mesmo que o passo diga "Commit". Implementar tudo, deixar as mudanças no working tree, e perguntar ao usuário no final se ele quer commitar.

**Goal:** Dar a cada categoria de produto (Anéis, Brincos, Colares, Pulseiras, Mais Vendidos) uma URL própria e indexável (`/categoria/<slug>/`), com canônica, título e descrição corretos, para que possam rankear individualmente no Google — sem quebrar a navegação por query string (`/?categoria=anel`) que já existe hoje.

**Architecture:** Extrai a lógica de filtro/ordenação/paginação que hoje vive dentro de `home()` para uma função compartilhada, reaproveitada por uma nova `categoria_view()`. O template `home.html` é reaproveitado (não duplicado) para as duas rotas, ganhando um bloco condicional de "intro de categoria" e passando a montar `action`/links de forma dinâmica (em vez de sempre `"/"`), para não "vazar" de volta pra URL antiga ao trocar ordenação ou pesquisar dentro de uma página de categoria.

**Tech Stack:** Django (views, urls, templates, sitemaps), SQLite/Postgres via Django ORM, testes com `django.test.TestCase`.

---

## Descobertas importantes (leia antes de aprovar o plano)

1. **Slugs reais no banco:** consultei o banco e hoje só existem 4 categorias de verdade: `anel`, `brinco`, `colar`, `pulseira` (singular, é o que já está em `Categoria.slug`). Os links do menu para `choker` e `conjunto` **não correspondem a nenhuma `Categoria` no banco** — hoje eles só não quebram porque o filtro de `home()` simplesmente não acha nada e mostra a lista vazia. Por isso, neste plano:
   - Só crio URL própria para `anel`, `brinco`, `colar`, `pulseira` e a categoria virtual `mais-vendidos` (filtro `destaque=True`, que não é uma `Categoria` de verdade).
   - Os links de `choker`/`conjunto` no menu **continuam apontando pra `/?categoria=choker`** como hoje. Se eu trocasse esses links pra `/categoria/choker/` agora, eu criaria um link de menu que dá 404 em todo lugar do site, porque a categoria não existe. Quando você criar essas categorias de verdade no admin, é só me pedir pra estender os links — a view já vai funcionar automaticamente, porque ela busca a `Categoria` pelo slug.

2. **Bug que eu ia introduzir sem querer, achei a tempo:** o `<title>` da página (a aba do navegador / título que aparece no Google) está **hardcoded** em `home.html`:
   ```html
   {% block title %}Barrs Store — Semijoias modernas e exclusivas{% endblock %}
   ```
   Ele ignora completamente a variável `seo_title` que a view já calcula. Se eu reaproveitasse `home.html` pra `/categoria/anel/` sem mexer nisso, **todas as páginas de categoria teriam o título "Barrs Store — Semijoias modernas e exclusivas" no Google**, idêntico ao da home — destruindo boa parte do ganho de SEO que estamos buscando. O plano corrige isso (Tarefa 4), mas só para as páginas de categoria — a home continua com o título exato que já tem hoje, sem mudar nada pra ela.

3. **Formulários de busca/ordenação têm `action="/"` fixo.** Se eu só trocasse os links do menu sem mexer nisso, ao usar o campo de busca ou trocar a ordenação dentro de `/categoria/anel/`, você voltaria pra `/?categoria=anel&ordem=...` — desfazendo a URL nova a cada interação. O plano torna esses `action` dinâmicos (Tarefa 4).

4. **Paginação e infinite scroll não precisam de nenhuma mudança.** O JS de infinite scroll (`static/loja/js/home.js:198-203`) já monta a URL da próxima página com `location.pathname`, então funciona automaticamente em `/categoria/anel/?page=2` sem tocar no JS.

---

## Campos novos no model `Categoria` — confirme antes de eu aplicar a migração

Hoje `Categoria` (`loja/models.py:27-38`) só tem `nome`, `slug` e `icone`. Vou propor adicionar três campos, todos opcionais (não quebram nada que já existe):

```python
meta_title = models.CharField(
    max_length=70, blank=True, default='',
    help_text='Título customizado para Google/aba do navegador. Se vazio, usamos um título automático.',
)
meta_description = models.CharField(
    max_length=160, blank=True, default='',
    help_text='Resumo para Google, até 160 caracteres. Se vazio, usamos uma descrição automática.',
)
descricao_categoria = models.TextField(
    blank=True, default='',
    help_text='Texto introdutório exibido no topo da página da categoria (bom para SEO). Pode ficar vazio por enquanto.',
)
```

Isso vai gerar uma migração simples (`AddField` x3, sem alterar dados existentes). **Não vou rodar `makemigrations`/`migrate` até você confirmar esses três campos.**

---

## File Structure

| Arquivo | O que muda |
|---|---|
| `loja/models.py` | Adiciona 3 campos em `Categoria` |
| `loja/migrations/00XX_categoria_seo_fields.py` | Gerado pelo Django (`makemigrations`) |
| `loja/views.py` | Extrai `_filtrar_e_paginar_produtos()`, move `CATEGORIA_ALIASES` pro nível de módulo, refatora `home()`, cria `categoria_view()` |
| `loja/urls.py` | Adiciona rota `categoria/<slug:categoria_slug>/` |
| `loja/sitemaps.py` | Adiciona `CategoriaSitemap` |
| `loja/templates/home.html` | `action` dinâmico nos formulários, link "Limpar busca" dinâmico, bloco de intro de categoria, `<title>` dinâmico só quando há categoria |
| `loja/templates/partials/category_nav.html` | Links de Anéis/Brincos/Colares/Pulseiras/Mais vendidos passam a apontar pra `/categoria/<slug>/` |
| `loja/templates/partials/footer.html` | Mesmos 4 links atualizados |
| `static/loja/css/pages/home.css` | Estilo mínimo pro bloco de intro (`.categoria-intro`) |
| `loja/tests.py` | 3 testes novos |

---

### Tarefa 1: Campos de SEO no model `Categoria` (PARAR PARA CONFIRMAÇÃO)

**Files:**
- Modify: `loja/models.py:27-38`
- Create: `loja/migrations/00XX_categoria_seo_fields.py` (gerado pelo Django)

- [ ] **Passo 1: Adicionar os campos no model**

Em `loja/models.py`, dentro da classe `Categoria`:

```python
class Categoria(models.Model):
    nome = models.CharField(max_length=50)
    slug = models.SlugField(unique=True)
    icone = models.CharField(max_length=10, blank=True, default='💎', help_text='Emoji do ícone')
    meta_title = models.CharField(
        max_length=70, blank=True, default='',
        help_text='Título customizado para Google/aba do navegador. Se vazio, usamos um título automático.',
    )
    meta_description = models.CharField(
        max_length=160, blank=True, default='',
        help_text='Resumo para Google, até 160 caracteres. Se vazio, usamos uma descrição automática.',
    )
    descricao_categoria = models.TextField(
        blank=True, default='',
        help_text='Texto introdutório exibido no topo da página da categoria (bom para SEO). Pode ficar vazio por enquanto.',
    )

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nome']

    def __str__(self):
        return self.nome
```

- [ ] **Passo 2: PARAR — mostrar o diff pro usuário e esperar confirmação explícita antes de gerar a migração.**

- [ ] **Passo 3: Gerar a migração (só após confirmação)**

Run: `python manage.py makemigrations loja`
Expected: cria `loja/migrations/00XX_categoria_seo_fields.py` com 3 `AddField`.

- [ ] **Passo 4: Mostrar o conteúdo da migração gerada pro usuário antes de aplicar.**

- [ ] **Passo 5: Aplicar a migração (só após confirmação)**

Run: `python manage.py migrate loja`
Expected: `Applying loja.00XX_categoria_seo_fields... OK`

---

### Tarefa 2: Extrair lógica de listagem compartilhada (refatoração segura, com teste de regressão)

**Files:**
- Modify: `loja/views.py:1471-1581` (função `home`)
- Test: `loja/tests.py`

- [ ] **Passo 1: Escrever teste de regressão (trava o comportamento atual antes de mexer)**

Adicionar em `loja/tests.py`, logo depois da classe `HomeOrderingTests` (linha ~195):

```python
class HomeFiltroCategoriaQueryStringTests(TestCase):
    def test_query_string_categoria_filtra_produtos(self):
        categoria_aneis = Categoria.objects.create(nome='Aneis', slug='anel')
        categoria_colares = Categoria.objects.create(nome='Colares', slug='colar')
        anel = Produto.objects.create(
            nome='Anel Solitario',
            preco=Decimal('49.90'),
            estoque=5,
            categoria=categoria_aneis,
        )
        colar = Produto.objects.create(
            nome='Colar Gota',
            preco=Decimal('59.90'),
            estoque=5,
            categoria=categoria_colares,
        )

        response = Client().get('/?categoria=anel')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn(anel.nome, html)
        self.assertNotIn(colar.nome, html)
```

`Categoria` já está importado em `loja/tests.py` (verifique a lista de imports no topo — se não estiver, adicione `Categoria` ao `from .models import (...)`).

- [ ] **Passo 2: Rodar o teste e confirmar que já passa (comportamento atual, antes da refatoração)**

Run: `python manage.py test loja.tests.HomeFiltroCategoriaQueryStringTests -v 2`
Expected: `OK` (1 teste passando) — isso prova que o teste descreve corretamente o comportamento de hoje, antes de mexer em qualquer código.

- [ ] **Passo 3: Extrair `CATEGORIA_ALIASES` para o nível de módulo**

Em `loja/views.py`, logo acima da definição de `home` (linha 1471), adicionar:

```python
CATEGORIA_ALIASES = {
    'aneis': ['anel', 'aneis'],
    'anel': ['anel', 'aneis'],
    'brincos': ['brinco', 'brincos'],
    'brinco': ['brinco', 'brincos'],
    'colares': ['colar', 'colares'],
    'colar': ['colar', 'colares'],
    'pulseiras': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
    'pulseira': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
    'braceletes-e-pulseiras': ['pulseira', 'pulseiras', 'bracelete', 'braceletes', 'braceletes-e-pulseiras'],
    'chokers': ['choker', 'chokers'],
    'choker': ['choker', 'chokers'],
    'conjuntos': ['conjunto', 'conjuntos'],
    'conjunto': ['conjunto', 'conjuntos'],
}
```

- [ ] **Passo 4: Criar a função compartilhada `_filtrar_e_paginar_produtos`**

Logo abaixo de `CATEGORIA_ALIASES`:

```python
def _filtrar_e_paginar_produtos(request, categoria_slug, busca, ordem):
    """Filtra, ordena e pagina produtos. Usado por home() e categoria_view().

    Se a requisição for parcial (infinite scroll), retorna {'json_response': JsonResponse}.
    Caso contrário, retorna um dict com os dados prontos para o contexto do template.
    """
    produtos = Produto.objects.filter(visivel=True).distinct()

    if busca:
        produtos = produtos.filter(
            Q(nome__icontains=busca) | Q(descricao__icontains=busca)
        )

    if categoria_slug == 'mais-vendidos':
        produtos = produtos.filter(destaque=True)
    elif categoria_slug:
        produtos = produtos.filter(categoria__slug__in=CATEGORIA_ALIASES.get(categoria_slug, [categoria_slug]))

    if ordem == 'menor':
        produtos = produtos.order_by('-destaque', 'preco', '-criado_em', '-id')
    elif ordem == 'maior':
        produtos = produtos.order_by('-destaque', '-preco', '-criado_em', '-id')
    elif ordem == 'nome':
        produtos = produtos.order_by('-destaque', 'nome', '-criado_em', '-id')
    else:
        produtos = produtos.order_by('-destaque', '-criado_em', '-id')

    total_cache_key = f'home:count:v=1:q={busca}:o={ordem}:c={categoria_slug}'
    total_produtos = cache.get(total_cache_key)
    if total_produtos is None:
        total_produtos = produtos.count()
        cache.set(total_cache_key, total_produtos, 60)

    try:
        page_number = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page_number = 1
    per_page = 12
    query_params = request.GET.copy()
    query_params.pop('page', None)
    query_params.pop('partial', None)
    base_query = query_params.urlencode()

    is_partial = (
        request.GET.get('partial') == '1'
        or request.headers.get('x-requested-with') == 'XMLHttpRequest'
    )
    if is_partial:
        from django.template.loader import render_to_string
        inicio = (page_number - 1) * per_page
        fim = page_number * per_page
        chunk = list(produtos[inicio:fim])
        html = render_to_string('partials/product_cards_chunk.html', {'produtos': chunk}, request=request)
        return {
            'json_response': JsonResponse({
                'html': html,
                'has_next': total_produtos > fim,
                'next_page': page_number + 1 if total_produtos > fim else 0,
            })
        }

    produtos_pagina = produtos[:page_number * per_page]
    has_next_page = total_produtos > page_number * per_page
    next_page_url = ''
    if has_next_page:
        next_query = query_params.copy()
        next_query['page'] = page_number + 1
        next_page_url = f'?{next_query.urlencode()}#produtos'

    return {
        'produtos': produtos_pagina,
        'has_next_page': has_next_page,
        'next_page_url': next_page_url,
        'next_page_number': page_number + 1 if has_next_page else 0,
        'base_query': base_query,
        'total_produtos': total_produtos,
    }


def _montar_clear_busca_url(listing_base_url, categoria_slug, ordem):
    """Monta a URL do link 'Limpar busca', preservando categoria (só no modo query string) e ordem."""
    partes = []
    if listing_base_url == '/' and categoria_slug:
        partes.append(f'categoria={categoria_slug}')
    if ordem:
        partes.append(f'ordem={ordem}')
    if not partes:
        return listing_base_url
    return f"{listing_base_url}?{'&'.join(partes)}"
```

- [ ] **Passo 5: Reescrever `home()` para usar a função compartilhada**

Substituir o corpo de `home()` (linhas 1471-1581 de `loja/views.py`) por:

```python
def home(request):
    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')
    categoria_slug = request.GET.get('categoria', '')

    resultado = _filtrar_e_paginar_produtos(request, categoria_slug, busca, ordem)
    if 'json_response' in resultado:
        return resultado['json_response']

    categorias = cache.get('home:categorias:v=1')
    if categorias is None:
        categorias = list(Categoria.objects.all())
        cache.set('home:categorias:v=1', categorias, 300)

    # So noindex em buscas internas (q=); categoria e ordem continuam indexaveis.
    seo = seo_context(
        request,
        'Barrs Store - Acessorios modernos e exclusivos',
        'Compre acessorios femininos modernos na Barrs Store: aneis, brincos, colares e pulseiras com envio para todo o Brasil.',
        robots='noindex, follow' if request.GET.get('q') else 'index, follow',
    )

    context = {
        'produtos': resultado['produtos'],
        'has_next_page': resultado['has_next_page'],
        'next_page_url': resultado['next_page_url'],
        'next_page_number': resultado['next_page_number'],
        'base_query': resultado['base_query'],
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': resultado['total_produtos'],
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
        'categoria': None,
        'listing_base_url': '/',
        'clear_busca_url': _montar_clear_busca_url('/', categoria_slug, ordem),
    }
    context.update(seo)
    return render(request, 'home.html', context)
```

- [ ] **Passo 6: Rodar os testes de novo para confirmar que nada quebrou**

Run: `python manage.py test loja.tests.HomeOrderingTests loja.tests.HomeFiltroCategoriaQueryStringTests loja.tests.ProdutoSeoTests -v 2`
Expected: `OK` — os mesmos testes que passavam antes continuam passando depois da refatoração.

---

### Tarefa 3: Rota e view de categoria (`/categoria/<slug>/`)

**Files:**
- Modify: `loja/urls.py:12-18`
- Modify: `loja/views.py` (logo após `home()`, antes de `_registrar_clique_produto`)
- Test: `loja/tests.py`

- [ ] **Passo 1: Escrever os testes (vão falhar — a rota ainda não existe)**

Adicionar em `loja/tests.py`, depois de `HomeFiltroCategoriaQueryStringTests`:

```python
class CategoriaViewTests(TestCase):
    def test_pagina_categoria_lista_so_produtos_da_categoria_e_tem_canonica_propria(self):
        categoria_aneis = Categoria.objects.create(nome='Aneis', slug='anel')
        categoria_colares = Categoria.objects.create(nome='Colares', slug='colar')
        anel = Produto.objects.create(
            nome='Anel Solitario',
            preco=Decimal('49.90'),
            estoque=5,
            categoria=categoria_aneis,
        )
        colar = Produto.objects.create(
            nome='Colar Gota',
            preco=Decimal('59.90'),
            estoque=5,
            categoria=categoria_colares,
        )

        response = Client().get('/categoria/anel/')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn(anel.nome, html)
        self.assertNotIn(colar.nome, html)
        self.assertIn(
            '<link rel="canonical" href="https://www.barrsstore.com.br/categoria/anel/">',
            html,
        )

    def test_pagina_categoria_inexistente_retorna_404(self):
        response = Client().get('/categoria/categoria-que-nao-existe/')
        self.assertEqual(response.status_code, 404)

    def test_pagina_categoria_usa_meta_title_customizado_quando_definido(self):
        Categoria.objects.create(
            nome='Aneis',
            slug='anel',
            meta_title='Aneis femininos modernos | Barrs Store',
        )

        response = Client().get('/categoria/anel/')
        html = response.content.decode('utf-8')

        self.assertIn('<title>Aneis femininos modernos | Barrs Store</title>', html)

    def test_pagina_mais_vendidos_funciona_sem_categoria_no_banco(self):
        Produto.objects.create(
            nome='Colar Destaque Mais Vendido',
            preco=Decimal('99.90'),
            estoque=5,
            destaque=True,
        )

        response = Client().get('/categoria/mais-vendidos/')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Colar Destaque Mais Vendido', response.content.decode('utf-8'))
```

- [ ] **Passo 2: Rodar os testes e confirmar que falham (rota não existe ainda)**

Run: `python manage.py test loja.tests.CategoriaViewTests -v 2`
Expected: `FAIL` — erro do tipo `NoReverseMatch` ou 404 inesperado, porque `/categoria/anel/` ainda não existe.

- [ ] **Passo 3: Adicionar a rota em `loja/urls.py`**

Em `loja/urls.py`, adicionar logo após a linha `path('', views.home, name='home'),`:

```python
    path('categoria/<slug:categoria_slug>/', views.categoria_view, name='categoria_detalhe'),
```

- [ ] **Passo 4: Criar `categoria_view` em `loja/views.py`**

Adicionar logo após a função `home()` (antes de `_registrar_clique_produto`):

```python
def categoria_view(request, categoria_slug):
    categoria_obj = None
    if categoria_slug != 'mais-vendidos':
        categoria_obj = get_object_or_404(Categoria, slug=categoria_slug)

    busca = request.GET.get('q', '').strip()
    ordem = request.GET.get('ordem', '')

    resultado = _filtrar_e_paginar_produtos(request, categoria_slug, busca, ordem)
    if 'json_response' in resultado:
        return resultado['json_response']

    categorias = cache.get('home:categorias:v=1')
    if categorias is None:
        categorias = list(Categoria.objects.all())
        cache.set('home:categorias:v=1', categorias, 300)

    nome_categoria = categoria_obj.nome if categoria_obj else 'Mais vendidos'
    titulo_padrao = f'{nome_categoria} | Barrs Store'
    descricao_padrao = f'Confira {nome_categoria.lower()} na Barrs Store, com envio para todo o Brasil.'

    titulo_seo = (categoria_obj.meta_title if categoria_obj and categoria_obj.meta_title else titulo_padrao)
    descricao_seo = (
        categoria_obj.meta_description if categoria_obj and categoria_obj.meta_description else descricao_padrao
    )

    seo = seo_context(request, titulo_seo, descricao_seo)
    listing_base_url = reverse('categoria_detalhe', kwargs={'categoria_slug': categoria_slug})

    context = {
        'produtos': resultado['produtos'],
        'has_next_page': resultado['has_next_page'],
        'next_page_url': resultado['next_page_url'],
        'next_page_number': resultado['next_page_number'],
        'base_query': resultado['base_query'],
        'qtd_carrinho': get_carrinho_info(request),
        'busca': busca,
        'ordem': ordem,
        'total_produtos': resultado['total_produtos'],
        'categorias': categorias,
        'categoria_ativa': categoria_slug,
        'categoria': categoria_obj,
        'categoria_nome_exibicao': nome_categoria,
        'listing_base_url': listing_base_url,
        'clear_busca_url': _montar_clear_busca_url(listing_base_url, categoria_slug, ordem),
    }
    context.update(seo)
    return render(request, 'home.html', context)
```

- [ ] **Passo 5: Rodar os testes de novo e confirmar que passam**

Run: `python manage.py test loja.tests.CategoriaViewTests -v 2`
Expected: `OK` (4 testes) — exceto o teste do `<title>` customizado, que só vai passar depois da Tarefa 4 (que corrige o `<title>` hardcoded). Isso é esperado neste ponto; ele será resolvido no próximo passo.

---

### Tarefa 4: Ajustes no template `home.html` (título, formulários, bloco de intro)

**Files:**
- Modify: `loja/templates/home.html`
- Modify: `static/loja/css/pages/home.css`

- [ ] **Passo 1: Corrigir o `<title>` hardcoded (linha 4)**

Trocar:

```html
{% block title %}Barrs Store — Semijoias modernas e exclusivas{% endblock %}
```

Por:

```html
{% block title %}{% if categoria_ativa and listing_base_url != '/' %}{{ seo_title }}{% else %}Barrs Store — Semijoias modernas e exclusivas{% endif %}{% endblock %}
```

Isso preserva o título atual da home exatamente como está, e só usa o título dinâmico (`seo_title`, calculado em `categoria_view`) quando a página é uma página de categoria de verdade (rota nova).

- [ ] **Passo 2: Tornar os formulários de busca e ordenação dinâmicos (linhas 125 e 133)**

Trocar:

```html
  <form method="GET" action="/" class="controls__search" role="search" id="product-search-form">
```

Por:

```html
  <form method="GET" action="{{ listing_base_url }}" class="controls__search" role="search" id="product-search-form">
```

E trocar:

```html
    <form method="GET" action="/" class="controls__sort-form">
```

Por:

```html
    <form method="GET" action="{{ listing_base_url }}" class="controls__sort-form">
```

- [ ] **Passo 3: Tornar o campo oculto `categoria` condicional (linhas 129 e 135)**

Hoje existem duas ocorrências de:

```html
    {% if categoria_ativa %}<input type="hidden" name="categoria" value="{{ categoria_ativa }}">{% endif %}
```

Trocar **as duas** por:

```html
    {% if categoria_ativa and listing_base_url == '/' %}<input type="hidden" name="categoria" value="{{ categoria_ativa }}">{% endif %}
```

(Quando a categoria já está na URL via `/categoria/anel/`, não precisamos repeti-la como `?categoria=anel` — isso evitaria uma URL redundante tipo `/categoria/anel/?categoria=anel`.)

- [ ] **Passo 4: Usar `clear_busca_url` no link "Limpar busca" (linha 148)**

Trocar:

```html
  {{ total_produtos }} resultado{% if total_produtos != 1 %}s{% endif %} para "<strong>{{ busca }}</strong>" - <a href="/{% if categoria_ativa or ordem %}?{% if categoria_ativa %}categoria={{ categoria_ativa }}{% endif %}{% if categoria_ativa and ordem %}&{% endif %}{% if ordem %}ordem={{ ordem }}{% endif %}{% endif %}">Limpar busca</a>
```

Por:

```html
  {{ total_produtos }} resultado{% if total_produtos != 1 %}s{% endif %} para "<strong>{{ busca }}</strong>" - <a href="{{ clear_busca_url }}">Limpar busca</a>
```

- [ ] **Passo 5: Adicionar o bloco de intro de categoria**

Logo antes do comentário `<!-- GRID DE PRODUTOS -->` (linha 152), adicionar:

```html
{% if listing_base_url != '/' and categoria_ativa %}
<section class="categoria-intro">
  <h1 class="categoria-intro__title">{{ categoria_nome_exibicao }}</h1>
  {% if categoria and categoria.descricao_categoria %}
  <div class="categoria-intro__texto">{{ categoria.descricao_categoria|linebreaks }}</div>
  {% endif %}
</section>
{% endif %}
```

Esse bloco só aparece nas páginas `/categoria/...`, nunca na home com `?categoria=` (pra não mudar nada do que já existe na home hoje). O texto (`descricao_categoria`) começa vazio — você preenche depois pelo admin.

- [ ] **Passo 6: Estilo mínimo pro bloco novo**

Em `static/loja/css/pages/home.css`, adicionar perto da regra `.section__title` (linha ~488):

```css
.categoria-intro {
  margin-bottom: var(--space-6);
}
.categoria-intro__title {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--color-ink);
  margin-bottom: var(--space-2);
}
.categoria-intro__texto {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--color-ink-muted);
  max-width: 60ch;
}
```

- [ ] **Passo 7: Rodar a suíte de testes inteira da Tarefa 3 de novo — agora o teste do `<title>` deve passar**

Run: `python manage.py test loja.tests.CategoriaViewTests loja.tests.HomeOrderingTests loja.tests.HomeFiltroCategoriaQueryStringTests -v 2`
Expected: `OK` (todos os testes, incluindo o do `meta_title` customizado).

---

### Tarefa 5: Atualizar links de navegação

**Files:**
- Modify: `loja/templates/partials/category_nav.html`
- Modify: `loja/templates/partials/footer.html`

- [ ] **Passo 1: Atualizar `category_nav.html`**

Conteúdo atual completo, substituir por:

```html
<nav class="category-nav" aria-label="Categorias de produtos">
  <div class="category-nav__scroller">
    <a class="category-nav__link category-nav__link--all{% if request.GET.ver == 'todos' and not categoria_ativa %} is-active{% endif %}" href="/?ver=todos#produtos">
      Ver todos
      <span class="category-nav__chevron" aria-hidden="true">›</span>
    </a>
    <a class="category-nav__link{% if categoria_ativa == 'anel' %} is-active{% endif %}" href="/categoria/anel/#produtos">Anéis</a>
    <a class="category-nav__link{% if categoria_ativa == 'pulseira' %} is-active{% endif %}" href="/categoria/pulseira/#produtos">Braceletes e Pulseiras</a>
    <a class="category-nav__link{% if categoria_ativa == 'brinco' %} is-active{% endif %}" href="/categoria/brinco/#produtos">Brincos</a>
    <a class="category-nav__link{% if categoria_ativa == 'colar' %} is-active{% endif %}" href="/categoria/colar/#produtos">Colares</a>
    <a class="category-nav__link{% if categoria_ativa == 'choker' or categoria_ativa == 'chokers' %} is-active{% endif %}" href="/?categoria=choker#produtos">Chokers</a>
    <a class="category-nav__link{% if categoria_ativa == 'conjunto' or categoria_ativa == 'conjuntos' %} is-active{% endif %}" href="/?categoria=conjunto#produtos">Conjuntos</a>
    <a class="category-nav__link{% if categoria_ativa == 'mais-vendidos' %} is-active{% endif %}" href="/categoria/mais-vendidos/#produtos">Mais vendidos</a>
  </div>
</nav>
```

Note que `Chokers` e `Conjuntos` continuam com o link antigo (`/?categoria=...`) — eles não têm `Categoria` real no banco ainda (ver "Descobertas importantes" no topo deste plano).

- [ ] **Passo 2: Atualizar `footer.html` (linhas 54-57)**

Trocar:

```html
          <a href="/?categoria=brinco#produtos">Brincos</a>
          <a href="/?categoria=anel#produtos">Anéis</a>
          <a href="/?categoria=pulseira#produtos">Pulseiras</a>
          <a href="/?categoria=colar#produtos">Colares</a>
```

Por:

```html
          <a href="/categoria/brinco/#produtos">Brincos</a>
          <a href="/categoria/anel/#produtos">Anéis</a>
          <a href="/categoria/pulseira/#produtos">Pulseiras</a>
          <a href="/categoria/colar/#produtos">Colares</a>
```

- [ ] **Passo 3: Rodar a suíte completa de testes de `loja` pra garantir que nada mais quebrou**

Run: `python manage.py test loja -v 2`
Expected: `OK`, todos os testes passando (os já existentes + os novos das Tarefas 2 e 3).

---

### Tarefa 6: Adicionar categorias ao sitemap

**Files:**
- Modify: `loja/sitemaps.py`
- Modify: `loja/urls.py:7-10`

- [ ] **Passo 1: Criar `CategoriaSitemap` em `loja/sitemaps.py`**

```python
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Produto, Categoria


class ProdutoSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return Produto.objects.filter(visivel=True).order_by('-criado_em')

    def lastmod(self, obj):
        return obj.criado_em


class CategoriaSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Categoria.objects.all()

    def location(self, obj):
        return reverse('categoria_detalhe', kwargs={'categoria_slug': obj.slug})


class StaticViewSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6

    def items(self):
        return ['home', 'sobre', 'contato', 'entrega', 'garantia', 'politica', 'medidas', 'rastrear_pedido']

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return 1.0 if item == 'home' else 0.6
```

- [ ] **Passo 2: Registrar no `urls.py`**

Em `loja/urls.py`, trocar:

```python
from .sitemaps import ProdutoSitemap, StaticViewSitemap

sitemaps = {
    'produtos': ProdutoSitemap,
    'paginas': StaticViewSitemap,
}
```

Por:

```python
from .sitemaps import ProdutoSitemap, StaticViewSitemap, CategoriaSitemap

sitemaps = {
    'produtos': ProdutoSitemap,
    'categorias': CategoriaSitemap,
    'paginas': StaticViewSitemap,
}
```

A categoria virtual `mais-vendidos` (que não é uma `Categoria` de verdade) fica de fora do sitemap — ela continua acessível e indexável via link normal no menu, só não é "empurrada" ativamente pro Google. Se quiser incluí-la também depois, é só me avisar.

- [ ] **Passo 3: Conferir o sitemap manualmente**

Run: `python manage.py runserver` (em outro terminal) e depois `curl -s http://127.0.0.1:8000/sitemap.xml | grep -A1 "categoria/"`
Expected: ver as 4 URLs `https://www.barrsstore.com.br/categoria/anel/`, `.../brinco/`, `.../colar/`, `.../pulseira/` com `<priority>0.8</priority>`.

---

### Tarefa 7: Checagem final

**Files:** nenhum (apenas validação)

- [ ] **Passo 1: Rodar a suíte de testes completa do projeto**

Run: `python manage.py test loja -v 2`
Expected: `OK`, todos os testes passando.

- [ ] **Passo 2: Listar as URLs novas pra você testar manualmente**

Ao final desta tarefa, reportar pro usuário a lista exata de URLs novas para teste manual:
- `/categoria/anel/`
- `/categoria/brinco/`
- `/categoria/colar/`
- `/categoria/pulseira/`
- `/categoria/mais-vendidos/`
- `/categoria/anel/?ordem=menor` (checar que a ordenação funciona e a URL não volta pra `/?categoria=...`)
- `/categoria/anel/?page=2` (se houver produtos suficientes, checar paginação/infinite scroll)
- `/sitemap.xml` (conferir que as URLs de categoria aparecem)
- `/categoria/categoria-que-nao-existe/` (deve dar 404)

---

## Self-Review

**Cobertura do spec:**
1. Rotas próprias por categoria (`/categoria/<slug>/`) — Tarefa 3. ✅
2. View nova reaproveitando lógica de filtro da `home` — Tarefas 2 e 3. ✅
3. Paginação própria com ordenação em query string — Tarefa 2 (`_filtrar_e_paginar_produtos` já suporta `?page=`/`?ordem=` para qualquer `categoria_slug`) e Tarefa 4 (`action` dinâmico evita "vazar" pra URL antiga). ✅
4. Canônica correta automaticamente via `request.path` — não precisa de código extra, é consequência de `seo_context()` já existente; testado em `CategoriaViewTests`. ✅
5. Meta title/description customizáveis por categoria sem migração ainda — Tarefa 1 traz os campos propostos, com PARADA explícita antes de `makemigrations`/`migrate`. ✅
6. Bloco de texto introdutório reservado, vazio por padrão — Tarefa 4, Passo 5 (`descricao_categoria`). ✅
7. Atualizar links de navegação — Tarefa 5. ✅ (com a ressalva de `choker`/`conjunto` permanecerem como estão, documentada nas "Descobertas importantes")
8. Não quebrar `/?categoria=anel` existente, sem 404 — preservado integralmente; `home()` continua funcionando exatamente como hoje (testado em `HomeFiltroCategoriaQueryStringTests`). ✅
9. Sitemap com prioridade 0.8 — Tarefa 6. ✅
10. Não escrever texto de categoria, não aplicar migração sem confirmar, não quebrar navegação por query string — respeitado em todas as tarefas. ✅

**Achados extras fora do pedido original, mas necessários pra o pedido funcionar de verdade:**
- Correção do `<title>` hardcoded (Tarefa 4, Passo 1) — sem isso, todas as páginas de categoria teriam o mesmo título da home no Google.
- `action` dinâmico nos formulários de busca/ordenação (Tarefa 4, Passos 2-3) — sem isso, qualquer interação dentro de `/categoria/anel/` te jogaria de volta pra `/?categoria=anel`.

**Scan de placeholders:** nenhum "TBD"/"implementar depois" nos passos de código — todo trecho tem o código completo.
