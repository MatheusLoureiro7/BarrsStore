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
