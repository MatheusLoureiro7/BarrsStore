import re
import secrets
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden


SUSPICIOUS_PATH_RE = re.compile(
    r'('
    r'\.sql$|\.zip$|\.rar$|\.7z$|\.tar\.gz$|backup|dump|source|'
    r'/src/|/wp-admin/|/wp-includes/|/xmlrpc\.php|'
    # Scanners observados em produção (Railway logs) — devolve 403 silencioso
    r'^/meta\.json$|'
    r'/twint_ch\.js$|/qr_modal\.js$|/lkk_ch\.js$|/support_parent\.css$|'
    r'^/static/style/sys_files/'
    r')',
    re.IGNORECASE,
)


def _client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def _parse_rate(rate):
    amount, window = rate.split('/', 1)
    amount = int(amount)
    unit = window[-1]
    value = int(window[:-1] or 1)
    seconds = {'s': 1, 'm': 60, 'h': 3600}.get(unit, 60) * value
    return amount, seconds


class BlockScannerPathsMiddleware:
    """Bloqueia scanners comuns sem encostar em rotas legitimas como o webhook."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info or request.path
        if path.startswith('/pagamento/webhook/'):
            return self.get_response(request)
        if SUSPICIOUS_PATH_RE.search(path):
            return HttpResponseForbidden('Forbidden')
        return self.get_response(request)


class AdminRateLimitMiddleware:
    """Rate limit simples para acoes do painel, sem travar navegacao normal."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.limit, self.window = _parse_rate(getattr(settings, 'ADMIN_RATE_LIMIT', '60/5m'))

    def __call__(self, request):
        path = request.path_info or request.path
        if not (path.startswith('/painel/') or path.startswith('/admin/')):
            return self.get_response(request)
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return self.get_response(request)

        now = int(time.time())
        bucket = now // self.window
        key = f'admin-rate:{_client_ip(request)}:{bucket}'
        hits = cache.get(key, 0) + 1
        cache.set(key, hits, self.window + 30)
        if hits > self.limit:
            return HttpResponse('Too many requests', status=429)
        return self.get_response(request)


UTM_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid')


class CaptureUtmMiddleware:
    """Captura parametros UTM (e gclid/fbclid) em qualquer GET e persiste na sessao.

    Estrategia last-touch wins (igual GA4): a cada clique vindo de campanha,
    sobrescreve a origem anterior. O dicionario fica em `request.session['utm']`
    e e salvo no Pedido quando o checkout finalizar (campo origem_utm).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'GET':
            captados = {k: request.GET[k][:120] for k in UTM_KEYS if k in request.GET}
            if captados:
                request.session['utm'] = {**(request.session.get('utm') or {}), **captados}
                request.session.modified = True
        return self.get_response(request)


class ContentSecurityPolicyReportOnlyMiddleware:
    """Adiciona CSP em modo observacao ou bloqueio conforme a env CSP_ENFORCE.

    Gera um nonce por request e o injeta no header CSP substituindo o
    marcador `{nonce}`. Templates leem o nonce via context_processor
    como `{{ csp_nonce }}` para colocar em scripts inline confiaveis.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Gera o nonce ANTES de processar a view, para os templates poderem usa-lo.
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        policy = getattr(settings, 'CONTENT_SECURITY_POLICY', '')
        if policy:
            policy = policy.replace('{nonce}', request.csp_nonce)
            header = 'Content-Security-Policy' if getattr(settings, 'CSP_ENFORCE', False) else 'Content-Security-Policy-Report-Only'
            if header not in response:
                response[header] = policy
        path = request.path_info or request.path
        if path.startswith(('/pagamento/', '/finalizar/', '/minha-conta/')):
            response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
