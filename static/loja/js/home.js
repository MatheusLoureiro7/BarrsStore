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
        grid.insertAdjacentHTML('beforeend', data.html);
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
