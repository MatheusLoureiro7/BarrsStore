import re
import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden


SUSPICIOUS_PATH_RE = re.compile(
    r'(\.sql$|\.zip$|\.rar$|\.7z$|\.tar\.gz$|backup|dump|source|/src/|/wp-admin/|/wp-includes/|/xmlrpc\.php)',
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
    """Rate limit simples para o painel Django, antes do processamento do admin."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.limit, self.window = _parse_rate(getattr(settings, 'ADMIN_RATE_LIMIT', '20/5m'))

    def __call__(self, request):
        path = request.path_info or request.path
        if not (path.startswith('/painel/') or path.startswith('/admin/')):
            return self.get_response(request)

        now = int(time.time())
        bucket = now // self.window
        key = f'admin-rate:{_client_ip(request)}:{bucket}'
        hits = cache.get(key, 0) + 1
        cache.set(key, hits, self.window + 30)
        if hits > self.limit:
            return HttpResponse('Too many requests', status=429)
        return self.get_response(request)
