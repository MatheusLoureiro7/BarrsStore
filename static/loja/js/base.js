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
  const accountLink = pageData.userAuthenticated === 'true'
    ? `<a class="mobile-menu__link" href="${accountUrl}">Minha conta</a>`
    : `<a class="mobile-menu__link" href="${loginUrl}">Entrar</a>`;
  const logo = nav.querySelector('.nav__logo');
  const logoImg = logo ? logo.querySelector('img') : null;
  const logoSrc = logoImg ? logoImg.getAttribute('src') : '';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'nav__mobile-toggle';
  toggle.setAttribute('aria-label', 'Abrir menu');
  toggle.setAttribute('aria-controls', 'mobile-menu');
  toggle.setAttribute('aria-expanded', 'false');
  toggle.innerHTML = '<svg class="icon" aria-hidden="true"><path d="M5 7h14M5 12h14M5 17h14"/></svg>';
  nav.prepend(toggle);

  const mobileCart = document.createElement('a');
  mobileCart.href = cartUrl;
  mobileCart.className = 'nav__mobile-cart';
  mobileCart.setAttribute('aria-label', cartCount > 0 ? `Carrinho com ${cartCount} item(ns)` : 'Carrinho');
  mobileCart.innerHTML = `
    <svg class="icon" aria-hidden="true"><use href="#i-cart"></use></svg>
    ${cartCount > 0 ? `<span class="badge-count">${cartCount}</span>` : ''}
  `;
  nav.appendChild(mobileCart);

  const overlay = document.createElement('div');
  overlay.className = 'mobile-menu-overlay';
  overlay.setAttribute('hidden', '');

  const drawer = document.createElement('aside');
  drawer.id = 'mobile-menu';
  drawer.className = 'mobile-menu';
  drawer.setAttribute('aria-hidden', 'true');
  drawer.setAttribute('hidden', '');
  drawer.innerHTML = `
    <div class="mobile-menu__head">
      <a class="mobile-menu__brand" href="/">
        ${logoSrc ? `<img src="${logoSrc}" alt="Barrs Store" decoding="async">` : ''}
        <span>Barrs Store</span>
      </a>
      <button class="mobile-menu__close" type="button" aria-label="Fechar menu">
        <svg class="icon" aria-hidden="true"><use href="#i-close"></use></svg>
      </button>
    </div>
    <nav class="mobile-menu__nav" aria-label="Menu mobile">
      <a class="mobile-menu__link" href="/">Início</a>
      <details class="mobile-menu__group" open>
        <summary class="mobile-menu__summary">
          <span>Coleção</span>
          <svg class="icon" aria-hidden="true"><use href="#i-chevron-down"></use></svg>
        </summary>
        <div class="mobile-menu__sub">
          <a href="/#produtos">Ver todos os produtos</a>
          <a href="/medidas/">Guia de medidas</a>
          <a href="/garantia/">Garantia Barrs</a>
        </div>
      </details>
      <details class="mobile-menu__group">
        <summary class="mobile-menu__summary">
          <span>Atendimento</span>
          <svg class="icon" aria-hidden="true"><use href="#i-chevron-down"></use></svg>
        </summary>
        <div class="mobile-menu__sub">
          <a href="/contato/">Contato</a>
          <a href="/entrega/">Entrega e trocas</a>
          <a href="${trackUrl}">Rastrear pedido</a>
        </div>
      </details>
      <a class="mobile-menu__link" href="/sobre/">Sobre a Barrs</a>
      ${accountLink}
    </nav>
    <div class="mobile-menu__foot">
      <a class="mobile-menu__cta" href="${cartUrl}">Ver sacola</a>
      <a class="mobile-menu__muted" href="https://www.instagram.com/barrsstore" target="_blank" rel="noopener">Instagram @barrsstore</a>
    </div>
  `;

  document.body.appendChild(overlay);
  document.body.appendChild(drawer);

  const closeButton = drawer.querySelector('.mobile-menu__close');

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

