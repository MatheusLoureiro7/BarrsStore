(function () {
  var cfg = window.BARRS_PAYMENT_CONFIG;
  var mp = new MercadoPago(cfg.mpPublicKey, { locale: 'pt-BR' });

  var loadingEl    = document.getElementById('mp-loading');
  var errorEl      = document.getElementById('mp-erro');
  var statusEl     = document.getElementById('mp-status');
  var statusTextEl = document.getElementById('mp-status-text');
  var diretoEl     = document.getElementById('mp-direto');
  var diretoLinkEl = document.getElementById('mp-direto-link');
  var pixBoxEl     = document.getElementById('mp-pix-box');
  var pixQrEl      = document.getElementById('mp-pix-qr');
  var pixCodeEl    = document.getElementById('mp-pix-code');
  var pixCopyEl    = document.getElementById('mp-pix-copy');
  var pixStatusEl  = document.getElementById('mp-pix-status-link');
  var statusTimerId  = null;
  var statusInFlight = false;
  var statusStartedAt = 0;

  function showError(msg, options) {
    options = options || {};
    loadingEl.style.display = 'none';
    errorEl.style.display   = 'block';

    var titulo = msg || 'Não foi possível carregar o pagamento.';
    var sugestao = options.sugestao
      ? '<div class="co-error__hint">' + options.sugestao + '</div>'
      : '';

    var acao = (options.categoria === 'transient' || options.podeTentar !== false)
      ? '<a href="javascript:location.reload()" class="co-error__retry">Tentar novamente</a>'
      : '<a href="javascript:location.reload()" class="co-error__retry">Recarregar e usar outro pagamento</a>';

    errorEl.innerHTML = '<div class="co-error__title">' + titulo + '</div>' + sugestao + acao;
  }

  function showStatus(msg) {
    if (msg) {
      statusTextEl.textContent = msg;
      statusEl.style.display   = 'flex';
    } else {
      statusEl.style.display   = 'none';
    }
  }

  var overlayEl      = document.getElementById('mp-overlay');
  var overlayTitleEl = document.getElementById('mp-overlay-title');
  var overlaySubEl   = document.getElementById('mp-overlay-sub');
  var overlayRetryEl = document.getElementById('mp-overlay-retry');

  function showOverlay(state, options) {
    if (!overlayEl) return;
    options = options || {};
    overlayEl.classList.remove('is-loading', 'is-success', 'is-error');
    overlayEl.classList.add('is-' + state);
    overlayEl.hidden = false;
    document.body.style.overflow = 'hidden';

    if (state === 'loading') {
      overlayTitleEl.textContent = options.titulo || 'Processando seu pagamento...';
      overlaySubEl.textContent   = options.sub    || 'Aguarde alguns segundos, não feche esta página.';
      overlayRetryEl.hidden      = true;
    } else if (state === 'success') {
      overlayTitleEl.textContent = options.titulo || 'Pagamento confirmado!';
      overlaySubEl.textContent   = options.sub    || 'Estamos preparando seu pedido.';
      overlayRetryEl.hidden      = true;
    } else if (state === 'error') {
      overlayTitleEl.textContent = options.titulo || 'Não foi possível concluir o pagamento';
      overlaySubEl.textContent   = options.sub    || 'Verifique os dados e tente novamente.';
      overlayRetryEl.hidden      = false;
    }
  }

  function hideOverlay() {
    if (!overlayEl) return;
    overlayEl.hidden = true;
    overlayEl.classList.remove('is-loading', 'is-success', 'is-error');
    document.body.style.overflow = '';
  }

  if (overlayRetryEl) {
    overlayRetryEl.addEventListener('click', hideOverlay);
  }

  function startStatusPolling() {
    if (statusTimerId) return;
    statusStartedAt = Date.now();
    checkPedidoStatus();
    statusTimerId = setInterval(checkPedidoStatus, 5000);
  }

  function stopStatusPolling() {
    if (!statusTimerId) return;
    clearInterval(statusTimerId);
    statusTimerId = null;
  }

  async function checkPedidoStatus() {
    if (statusInFlight) return;
    if (statusStartedAt && Date.now() - statusStartedAt > 30 * 60 * 1000) {
      stopStatusPolling();
      return;
    }

    statusInFlight = true;
    try {
      var response = await fetch(cfg.urls.status, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) return;
      var data = await response.json();
      if (data.confirmado && data.sucesso_url) {
        stopStatusPolling();
        showStatus('Pagamento aprovado. Redirecionando...');
        window.location.href = data.sucesso_url;
      }
    } catch (error) {
      // Mantem a tela do Pix aberta e tenta novamente no proximo ciclo.
    } finally {
      statusInFlight = false;
    }
  }

  function getPixData(data) {
    var transactionData = (
      data &&
      data.point_of_interaction &&
      data.point_of_interaction.transaction_data
    ) || {};

    return {
      qrCode: transactionData.qr_code || '',
      qrBase64: transactionData.qr_code_base64 || '',
      ticketUrl: transactionData.ticket_url || '',
    };
  }

  function showPixPayment(data) {
    var pix = getPixData(data);
    if (!pix.qrCode && !pix.qrBase64 && !pix.ticketUrl) return false;

    showStatus('');
    loadingEl.style.display = 'none';
    errorEl.style.display = 'none';
    pixBoxEl.classList.add('is-visible');
    pixCodeEl.value = pix.qrCode || pix.ticketUrl;
    pixStatusEl.href = data.redirect_url || cfg.urls.pendente;

    if (pix.qrBase64) {
      pixQrEl.src = pix.qrBase64.startsWith('data:image')
        ? pix.qrBase64
        : 'data:image/png;base64,' + pix.qrBase64;
      pixQrEl.hidden = false;
    } else {
      pixQrEl.hidden = true;
    }

    pixBoxEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    startStatusPolling();
    return true;
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible') checkPedidoStatus();
  });

  pixCopyEl.addEventListener('click', async function () {
    var code = pixCodeEl.value;
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      pixCopyEl.textContent = 'Codigo copiado';
      setTimeout(function () { pixCopyEl.textContent = 'Copiar codigo Pix'; }, 2200);
    } catch (err) {
      pixCodeEl.focus();
      pixCodeEl.select();
      document.execCommand('copy');
    }
  });

  async function iniciarPagamento() {
    try {
      var prefResp = await fetch(cfg.urls.preferencia, {
        method: 'POST',
        headers: {
          'X-CSRFToken':  cfg.csrfToken,
          'Content-Type': 'application/json',
        },
      });
      if (!prefResp.ok) throw new Error('Não foi possível iniciar o pagamento.');
      var prefData = await prefResp.json();

      if (prefData.init_point) {
        diretoLinkEl.href      = prefData.init_point;
        diretoEl.style.display = 'block';
      }

      var bricksBuilder = mp.bricks();
      await bricksBuilder.create('payment', 'paymentBrick_container', {
        initialization: {
          amount: cfg.total,
          payer: {
            entityType: 'individual',
            firstName: cfg.payerFirstName,
            lastName:  cfg.payerLastName,
            email:     cfg.payerEmail,
            identification: {
              type: 'CPF',
              number: cfg.payerCpf,
            },
          },
        },

        customization: {
          visual: {
            style: {
              theme: 'default',
              customVariables: {
                textPrimaryColor:      '#3D352C',
                textSecondaryColor:    '#9A9188',
                inputBackgroundColor:  '#FFFFFF',
                formBackgroundColor:   '#FFFFFF',
                baseColor:             '#6B7A64',
                baseColorFirstVariant: '#5D6C57',
                baseColorSecondVariant:'#E8EDE3',
                errorColor:            '#A85D52',
                successColor:          '#6B7A64',
                outlinePrimaryColor:   '#E0D8CF',
                outlineSecondaryColor: '#EDE7DE',
                buttonTextColor:       '#FFFFFF',
                fontSizeSmall:         '11px',
                fontSizeMedium:        '13px',
                fontSizeLarge:         '15px',
                fontWeightNormal:      '400',
                fontWeightSemiBold:    '600',
                borderRadiusSmall:     '6px',
                borderRadiusMedium:    '8px',
                borderRadiusLarge:     '12px',
                formPadding:           '16px',
              },
            },
          },

          paymentMethods: {
            creditCard:      'all',
            bankTransfer:    'all',
            maxInstallments: 6,
          },

          texts: {
            formTitle:                '',
            emailSectionTitle:        'Seus dados',
            installmentsSectionTitle: 'Parcelamento',
            cardholderName: {
              label:       'Nome no cartão',
              placeholder: 'Como aparece no cartão',
            },
            email: {
              label:       'E-mail',
              placeholder: 'seu@email.com',
            },
            cardholderIdentification: {
              label: 'CPF',
            },
            cardNumber: {
              label:       'Número do cartão',
              placeholder: '0000 0000 0000 0000',
            },
            expirationDate: {
              label:       'Validade',
              placeholder: 'MM/AA',
            },
            securityCode: {
              label:       'Código de segurança',
              placeholder: 'CVV',
            },
            financialInstitution: {
              label:       'Banco',
              placeholder: 'Selecione seu banco',
            },
            selectInstallments: 'Selecione as parcelas',
            selectIssuerBank:   'Banco emissor',
            formSubmit:         'Confirmar pagamento',
            paymentMethods: {
              newCreditCardTitle:  'Novo cartão de crédito',
              creditCardTitle:     'Cartão de crédito',
              creditCardValueProp: 'Parcele em até 6x',
              newDebitCardTitle:   'Novo cartão de débito',
              debitCardTitle:      'Cartão de débito',
              debitCardValueProp:  'Aprovação imediata',
              ticketTitle:         'Pix',
              ticketValueProp:     'Aprovação instantânea',
            },
            reviewConfirm: {
              componentTitle:           'Revise seu pedido',
              payerDetailsTitle:        'Seus dados',
              shippingDetailsTitle:     'Entrega',
              billingDetailsTitle:      'Cobrança',
              paymentMethodDetailsTitle:'Forma de pagamento',
              detailsTitle:             'Detalhes',
              summaryItemsTitle:        'Itens',
              summaryShippingTitle:     'Frete',
              summaryDiscountTitle:     'Desconto',
              summaryYouPayTitle:       'Você paga',
              summaryTotalTitle:        'Total',
            },
          },
        },

        callbacks: {
          onReady: function () {
            loadingEl.style.display = 'none';
          },

          onSubmit: function (_ref) {
            var formData = _ref.formData;
            showStatus('Processando pagamento com segurança...');
            showOverlay('loading');
            return fetch(cfg.urls.processar, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken':  cfg.csrfToken,
              },
              body: JSON.stringify(formData),
            })
              .then(async function (response) {
                var data = await response.json().catch(function () { return {}; });
                if (!response.ok) {
                  var erro = new Error(
                    data.erro || 'Pagamento não aprovado. Confira os dados e tente novamente.'
                  );
                  erro.sugestao   = data.sugestao || '';
                  erro.categoria  = data.categoria || '';
                  erro.podeTentar = data.pode_tentar !== false;
                  throw erro;
                }
                if ((data.status === 'pending' || data.status === 'in_process') && showPixPayment(data)) {
                  hideOverlay();
                  return;
                }
                if (data.redirect_url) {
                  showOverlay('success');
                  setTimeout(function () { window.location.href = data.redirect_url; }, 1400);
                }
              })
              .catch(function (error) {
                showStatus('');
                var subMsg = error.sugestao || 'Verifique os dados do cartão e tente novamente.';
                showOverlay('error', { titulo: error.message, sub: subMsg });
                showError(error.message, {
                  sugestao:   error.sugestao,
                  categoria:  error.categoria,
                  podeTentar: error.podeTentar,
                });
                throw error;
              });
          },

          onError: function (error) {
            console.error('[MP Brick]', error);
            showError('Não foi possível carregar o pagamento.');
          },
        },
      });

    } catch (error) {
      console.error('[iniciarPagamento]', error);
      showError('Não foi possível carregar o pagamento.');
    }
  }

  iniciarPagamento();
}());
