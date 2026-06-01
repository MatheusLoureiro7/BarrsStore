document.addEventListener('DOMContentLoaded', function () {
  const nav = document.querySelector('.nav');
  if (!nav || nav.dataset.mobileReady === 'true') return;

  nav.dataset.mobileReady = 'true';

  const pageData = document.body.dataset;
  const cartCount = Number(pageData.cartCount || 0) || 0;
  const cartUrl = pageData.cartUrl || '/carrinho/';
  const loginUrl = pageData.loginUrl || '/login/';
  const accountUrl = pageData.accountUrl || '/minha-conta/';
  const trackUrl = pageData.trackUrl || '/rastrear-pedido/';
  const userAuthed = pageData.userAuthenticated === 'true';
  const logo = nav.querySelector('.nav__logo');
  const logoImg = logo ? logo.querySelector('img') : null;
  const logoSrc = logoImg ? logoImg.getAttribute('src') : '';

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const key in attrs) {
        if (key === 'class') node.className = attrs[key];
        else if (key === 'html') node.innerHTML = attrs[key];
        else node.setAttribute(key, attrs[key]);
      }
    }
    if (children) {
      children.forEach(function (child) {
        if (child == null) return;
        node.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
      });
    }
    return node;
  }

  const toggle = el('button', {
    type: 'button',
    class: 'nav__mobile-toggle',
    'aria-label': 'Abrir menu',
    'aria-controls': 'mobile-menu',
    'aria-expanded': 'false',
    html: '<svg class="icon" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14"/></svg>',
  });
  nav.prepend(toggle);

  const mobileCart = el('a', {
    href: cartUrl,
    class: 'nav__mobile-cart',
    'aria-label': cartCount > 0 ? 'Carrinho com ' + cartCount + ' item(ns)' : 'Carrinho',
  });
  mobileCart.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-cart"></use></svg>';
  if (cartCount > 0) {
    const badge = el('span', { class: 'badge-count' }, [String(cartCount)]);
    mobileCart.appendChild(badge);
  }
  nav.appendChild(mobileCart);

  const overlay = el('div', { class: 'mobile-menu-overlay', hidden: '' });

  const drawer = el('aside', {
    id: 'mobile-menu',
    class: 'mobile-menu',
    'aria-hidden': 'true',
    hidden: '',
  });

  const head = el('div', { class: 'mobile-menu__head' });
  const brand = el('a', { class: 'mobile-menu__brand', href: '/' });
  if (logoSrc) {
    const img = el('img', { src: logoSrc, alt: 'Barrs Store', decoding: 'async' });
    brand.appendChild(img);
  }
  brand.appendChild(el('span', null, ['Barrs Store']));
  head.appendChild(brand);
  const closeButton = el('button', {
    class: 'mobile-menu__close',
    type: 'button',
    'aria-label': 'Fechar menu',
    html: '<svg class="icon" aria-hidden="true"><use href="#i-close"></use></svg>',
  });
  head.appendChild(closeButton);
  drawer.appendChild(head);

  const menuNav = el('nav', { class: 'mobile-menu__nav', 'aria-label': 'Menu mobile' });
  menuNav.appendChild(el('a', { class: 'mobile-menu__link', href: '/' }, ['Início']));

  const grupoColecao = el('details', { class: 'mobile-menu__group', open: '' });
  grupoColecao.innerHTML =
    '<summary class="mobile-menu__summary">' +
    '<span>Coleção</span>' +
    '<svg class="icon" aria-hidden="true"><use href="#i-chevron-down"></use></svg>' +
    '</summary>' +
    '<div class="mobile-menu__sub">' +
    '<a href="/#produtos">Ver todos os produtos</a>' +
    '<a href="/?categoria=anel#produtos">Anéis</a>' +
    '<a href="/?categoria=pulseira#produtos">Braceletes e Pulseiras</a>' +
    '<a href="/?categoria=brinco#produtos">Brincos</a>' +
    '<a href="/?categoria=colar#produtos">Colares</a>' +
    '<a href="/?categoria=choker#produtos">Chokers</a>' +
    '<a href="/?categoria=conjunto#produtos">Conjuntos</a>' +
    '<a href="/?categoria=mais-vendidos#produtos">Mais vendidos</a>' +
    '<a href="/medidas/">Guia de medidas</a>' +
    '<a href="/garantia/">Garantia Barrs</a>' +
    '</div>';
  menuNav.appendChild(grupoColecao);

  const grupoAtend = el('details', { class: 'mobile-menu__group' });
  const summaryAtend = el('summary', {
    class: 'mobile-menu__summary',
    html: '<span>Atendimento</span><svg class="icon" aria-hidden="true"><use href="#i-chevron-down"></use></svg>',
  });
  const subAtend = el('div', { class: 'mobile-menu__sub' });
  subAtend.appendChild(el('a', { href: '/contato/' }, ['Contato']));
  subAtend.appendChild(el('a', { href: '/entrega/' }, ['Entrega e trocas']));
  subAtend.appendChild(el('a', { href: trackUrl }, ['Rastrear pedido']));
  grupoAtend.appendChild(summaryAtend);
  grupoAtend.appendChild(subAtend);
  menuNav.appendChild(grupoAtend);

  menuNav.appendChild(el('a', { class: 'mobile-menu__link', href: '/sobre/' }, ['Sobre a Barrs']));
  menuNav.appendChild(el('a', {
    class: 'mobile-menu__link',
    href: userAuthed ? accountUrl : loginUrl,
  }, [userAuthed ? 'Minha conta' : 'Entrar']));
  drawer.appendChild(menuNav);

  const foot = el('div', { class: 'mobile-menu__foot' });
  foot.appendChild(el('a', { class: 'mobile-menu__cta', href: cartUrl }, ['Ver sacola']));
  foot.appendChild(el('a', {
    class: 'mobile-menu__muted',
    href: 'https://www.instagram.com/barrsstore',
    target: '_blank',
    rel: 'noopener',
  }, ['Instagram @barrsstore']));
  drawer.appendChild(foot);

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);

  function openMenu() {
    overlay.removeAttribute('hidden');
    drawer.removeAttribute('hidden');
    requestAnimationFrame(function () {
      document.body.classList.add('mobile-menu-open');
      toggle.setAttribute('aria-expanded', 'true');
      drawer.setAttribute('aria-hidden', 'false');
      const first = drawer.querySelector('a, button, summary');
      if (first) first.focus({ preventScroll: true });
    });
  }

  function closeMenu() {
    document.body.classList.remove('mobile-menu-open');
    toggle.setAttribute('aria-expanded', 'false');
    drawer.setAttribute('aria-hidden', 'true');
    window.setTimeout(function () {
      if (!document.body.classList.contains('mobile-menu-open')) {
        overlay.setAttribute('hidden', '');
        drawer.setAttribute('hidden', '');
      }
    }, 280);
  }

  toggle.addEventListener('click', openMenu);
  overlay.addEventListener('click', closeMenu);
  closeButton.addEventListener('click', closeMenu);
  drawer.addEventListener('click', function (event) {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && document.body.classList.contains('mobile-menu-open')) closeMenu();
  });
});

// ── Reveal-on-scroll: aplica .is-visible quando seção entra na viewport
(function () {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  var targets = document.querySelectorAll('[data-reveal]');
  if (!targets.length || !('IntersectionObserver' in window)) {
    // Sem IO → mostra tudo direto pra nao quebrar layout
    targets.forEach(function (el) { el.classList.add('is-visible'); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        io.unobserve(entry.target);
      }
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
  targets.forEach(function (el) { io.observe(el); });
})();

// ── Sticky header: aciona .is-scrolled após pequeno scroll ─────────
(function () {
  var nav = document.querySelector('.nav');
  if (!nav) return;
  var threshold = 12;
  var raf = null;
  function apply() {
    raf = null;
    nav.classList.toggle('is-scrolled', window.scrollY > threshold);
  }
  function onScroll() {
    if (raf == null) raf = requestAnimationFrame(apply);
  }
  apply();
  window.addEventListener('scroll', onScroll, { passive: true });
})();

// ── Toast (Django messages) — auto-dismiss + close on click ────────
(function () {
  var toasts = document.querySelectorAll('[data-bs-toast]');
  if (!toasts.length) return;
  function dismiss(t) {
    if (!t || t.classList.contains('is-leaving')) return;
    t.classList.add('is-leaving');
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 240);
  }
  toasts.forEach(function (t, i) {
    var btn = t.querySelector('[data-bs-toast-close]');
    if (btn) btn.addEventListener('click', function () { dismiss(t); });
    var isError = t.classList.contains('bs-toast--error');
    setTimeout(function () { dismiss(t); }, isError ? 6000 : 3600 + i * 200);
  });
})();

// ── Newsletter footer — captura celular e salva como Lead ─────────
(function () {
  var forms = document.querySelectorAll('[data-bs-newsletter]');
  if (!forms.length) return;
  var STORAGE_KEY = 'bs_newsletter_optin';
  forms.forEach(function (form) {
    var wrap = form.closest('.bs-newsletter');
    if (!wrap) return;
    var input = form.querySelector('input[name="telefone"]');
    if (!input) return;
    var btn = form.querySelector('button[type="submit"]');

    try {
      if (localStorage.getItem(STORAGE_KEY)) wrap.classList.add('is-sent');
    } catch (e) { /* storage indisponível */ }

    // Máscara (11) 99999-9999
    input.addEventListener('input', function () {
      var v = input.value.replace(/\D/g, '').slice(0, 11);
      if (v.length > 6) v = '(' + v.slice(0, 2) + ') ' + v.slice(2, 7) + '-' + v.slice(7);
      else if (v.length > 2) v = '(' + v.slice(0, 2) + ') ' + v.slice(2);
      input.value = v;
    });

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var digits = (input.value || '').replace(/\D/g, '');
      if (digits.length < 10) {
        input.focus();
        input.setAttribute('aria-invalid', 'true');
        input.style.borderColor = 'rgba(212,92,82,0.55)';
        return;
      }
      input.removeAttribute('aria-invalid');
      input.style.borderColor = '';

      var csrf = (form.querySelector('input[name="csrfmiddlewaretoken"]') || {}).value || '';
      var url  = form.dataset.url || '/lead/footer/';
      if (btn) { btn.disabled = true; btn.textContent = 'Aguarde...'; }

      fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'X-CSRFToken': csrf,
        },
        body: 'telefone=' + encodeURIComponent(digits),
        credentials: 'same-origin',
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.ok) {
            wrap.classList.add('is-sent');
            try { localStorage.setItem(STORAGE_KEY, '1'); } catch (ex) { /* ignore */ }
          } else {
            if (btn) { btn.disabled = false; btn.textContent = 'Inscrever-se'; }
            input.setAttribute('aria-invalid', 'true');
            input.style.borderColor = 'rgba(212,92,82,0.55)';
          }
        })
        .catch(function () {
          if (btn) { btn.disabled = false; btn.textContent = 'Inscrever-se'; }
        });
    });
  });
})();
