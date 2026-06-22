// Select de ordenacao: envia o formulario sozinho ao trocar (sem handler inline, exigido pelo CSP).
(function () {
  const sortSelect = document.querySelector('.controls__sort');
  if (!sortSelect) return;
  sortSelect.addEventListener('change', function () {
    this.form.submit();
  });
})();

// Carrossel mobile da faixa de confianca (proof-strip).
(function () {
  const strip = document.querySelector('.proof-strip');
  const track = document.querySelector('.proof-strip__inner');
  const dotsWrap = document.querySelector('.proof-strip__dots');
  if (!strip || !track || !dotsWrap) return;

  const items = Array.from(track.querySelectorAll('.proof-item'));
  if (items.length <= 1) return;

  const mobileQuery = window.matchMedia('(max-width: 767px)');
  let index = 0;
  let timer = null;
  let startX = 0;
  let deltaX = 0;
  let pausedUntil = 0;

  dotsWrap.innerHTML = items.map((_, i) =>
    `<button type="button" class="proof-strip__dot" aria-label="Mostrar benefício ${i + 1}"></button>`
  ).join('');
  const dots = Array.from(dotsWrap.querySelectorAll('.proof-strip__dot'));

  function setActive(nextIndex, userAction) {
    index = (nextIndex + items.length) % items.length;
    track.style.setProperty('--proof-index', index);
    items.forEach((item, i) => item.classList.toggle('is-active', i === index));
    dots.forEach((dot, i) => dot.classList.toggle('is-active', i === index));
    if (userAction) pauseBriefly();
  }

  function pauseBriefly() {
    pausedUntil = Date.now() + 5200;
  }

  function stop() {
    if (timer) window.clearInterval(timer);
    timer = null;
  }

  function play() {
    stop();
    if (!mobileQuery.matches) return;
    timer = window.setInterval(function () {
      if (Date.now() < pausedUntil) return;
      setActive(index + 1, false);
    }, 3200);
  }

  function configure() {
    if (mobileQuery.matches) {
      setActive(index, false);
      play();
    } else {
      stop();
      track.style.removeProperty('--proof-index');
      items.forEach((item) => item.classList.remove('is-active'));
      dots.forEach((dot) => dot.classList.remove('is-active'));
    }
  }

  dots.forEach((dot, i) => {
    dot.addEventListener('click', function () {
      setActive(i, true);
    });
  });

  strip.addEventListener('pointerdown', function (event) {
    if (!mobileQuery.matches) return;
    startX = event.clientX;
    deltaX = 0;
    pauseBriefly();
  }, { passive: true });

  strip.addEventListener('pointermove', function (event) {
    if (!mobileQuery.matches || !startX) return;
    deltaX = event.clientX - startX;
  }, { passive: true });

  strip.addEventListener('pointerup', function () {
    if (!mobileQuery.matches || !startX) return;
    if (Math.abs(deltaX) > 38) {
      setActive(index + (deltaX < 0 ? 1 : -1), true);
    }
    startX = 0;
    deltaX = 0;
  }, { passive: true });

  strip.addEventListener('mouseenter', pauseBriefly);
  strip.addEventListener('focusin', pauseBriefly);
  mobileQuery.addEventListener('change', configure);
  configure();
})();


// AddToCart dos cards sem recarregar a pagina.
// Usa event delegation para cobrir tambem cards adicionados via infinite scroll.
(function () {
  if (typeof document === 'undefined') return;
  const cartUrl = document.body?.dataset?.cartUrl || '/carrinho/';

  function updateCartBadges(count) {
    if (!Number.isFinite(count)) return;
    document.body.dataset.cartCount = String(count);
    document.querySelectorAll('.badge-count').forEach((badge) => {
      badge.textContent = String(count);
    });
    document.querySelectorAll('a[href="' + cartUrl + '"], a[href="' + cartUrl.replace(/\/$/, '') + '"]').forEach((link) => {
      let badge = link.querySelector('.badge-count');
      if (!badge && count > 0) {
        badge = document.createElement('span');
        badge.className = 'badge-count';
        link.appendChild(badge);
      }
      if (badge) badge.textContent = String(count);
    });
  }

  function showAddFeedback(button, message) {
    if (!button) return;
    const original = button.textContent;
    button.textContent = '✓';
    button.classList.add('is-added');
    button.setAttribute('aria-label', message || 'Produto adicionado ao carrinho');
    window.setTimeout(() => {
      button.textContent = original || '+';
      button.classList.remove('is-added');
    }, 1100);
  }

  function showBsToast(msg) {
    if (typeof window.bsToast !== 'function') return;
    window.bsToast(msg, { action: { label: 'Ver carrinho', href: '/carrinho/' } });
  }

  function logMetaPixelEvent(eventName, payload, options) {
    if (typeof window.logMetaPixelEvent === 'function') {
      window.logMetaPixelEvent(eventName, payload, options || {});
    } else {
      console.log('[META PIXEL]', eventName, payload || {}, options || {});
    }
  }

  // Gera (uma vez por form) o event_id de deduplicacao e o injeta como hidden input.
  // Assim o mesmo id vai no Pixel (eventID) e no POST (meta_event_id) -> Meta deduplica
  // o AddToCart do navegador com o da Conversions API. O FormData(form) abaixo o captura.
  function metaEventId(form) {
    // Gera um event_id NOVO a cada clique (sem cachear): re-adicionar o mesmo
    // produto sem recarregar a pagina deve contar como um novo AddToCart, nao
    // como duplicata. O id e gravado no hidden input; o listener de AJAX abaixo
    // (que roda depois, no MESMO submit) o reaproveita via FormData -> Pixel e
    // CAPI usam o mesmo id e o Meta deduplica corretamente os dois lados.
    const id = (window.crypto && crypto.randomUUID)
      ? 'atc_' + crypto.randomUUID()
      : 'atc_' + Date.now() + '_' + Math.random().toString(36).slice(2);
    let input = form.querySelector('input[name="meta_event_id"]');
    if (!input) {
      input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'meta_event_id';
      form.appendChild(input);
    }
    input.value = id;
    console.log('[META EVENT ID]', 'AddToCart', { frontend: id });
    return id;
  }

  document.addEventListener('submit', function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.pixelAdd !== '1') return;
    // Sempre gera o event_id (mesmo sem fbq): o POST levara meta_event_id para a CAPI
    // cobrir o evento caso o Pixel esteja bloqueado por adblocker.
    const eventId = metaEventId(form);
    if (typeof fbq !== 'function') return;
    const valor = Number(String(form.dataset.pixelValue || '0').replace(',', '.')) || 0;
    const pid = String(form.dataset.pixelId || '');
    const payload = {
      content_ids: [pid],
      content_type: 'product',
      content_name: form.dataset.pixelName || '',
      contents: [{ id: pid, quantity: 1 }],
      value: valor,
      currency: 'BRL',
    };
    const options = { eventID: eventId };
    logMetaPixelEvent('AddToCart', payload, options);
    fbq('track', 'AddToCart', payload, options);
  }, true);

  document.addEventListener('submit', async function (event) {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.pixelAdd !== '1') return;
    if (!('fetch' in window) || !('FormData' in window)) return;

    event.preventDefault();
    const button = form.querySelector('.product-card__add');
    if (button) button.disabled = true;

    try {
      const res = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: {
          'X-Requested-With': 'XMLHttpRequest',
          'Accept': 'application/json',
        },
        credentials: 'same-origin',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.erro || 'Nao foi possivel adicionar.');
      updateCartBadges(Number(data.cart_count));
      showAddFeedback(button, data.message);
      showBsToast(data.message || 'Produto adicionado ao carrinho!');
    } catch (error) {
      form.submit();
    } finally {
      if (button) button.disabled = false;
    }
  });
})();


// Infinite scroll: substitui o "Carregar mais" sem causar scroll-to-top nem reload.
(function () {
  const sentinel = document.getElementById('infinite-sentinel');
  const grid = document.getElementById('product-grid');
  const loader = document.getElementById('infinite-loader');
  const endMsg = document.getElementById('infinite-end');
  if (!sentinel || !grid) return;
  if (!('IntersectionObserver' in window) || !('fetch' in window)) return;

  let nextPage = parseInt(sentinel.dataset.nextPage, 10) || 0;
  const baseQuery = sentinel.dataset.baseQuery || '';
  let loading = false;
  let done = nextPage === 0;

  function buildUrl(page) {
    const params = new URLSearchParams(baseQuery);
    params.set('page', String(page));
    params.set('partial', '1');
    return location.pathname + '?' + params.toString();
  }

  function showLoader(on) {
    if (!loader) return;
    loader.hidden = !on;
  }

  function finish() {
    done = true;
    observer.disconnect();
    if (endMsg) endMsg.hidden = false;
  }

  async function loadNext() {
    if (loading || done) return;
    loading = true;
    showLoader(true);
    try {
      const res = await fetch(buildUrl(nextPage), {
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      if (data && data.html) {
        const template = document.createElement('template');
        template.innerHTML = data.html.trim();
        template.content.querySelectorAll('[data-product-id]').forEach((card) => {
          const id = card.getAttribute('data-product-id');
          if (!id || grid.querySelector('[data-product-id="' + id + '"]')) return;
          grid.appendChild(card);
        });
      }
      if (data && data.has_next && data.next_page) {
        nextPage = data.next_page;
      } else {
        finish();
      }
    } catch (err) {
      // Em falha, encerra o auto-load mas mantem a pagina utilizavel.
      console.warn('[home] Falha ao carregar mais produtos:', err);
      finish();
    } finally {
      loading = false;
      showLoader(false);
    }
  }

  const observer = new IntersectionObserver(function (entries) {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        loadNext();
        break;
      }
    }
  }, { rootMargin: '600px 0px 600px 0px', threshold: 0 });

  observer.observe(sentinel);
})();
