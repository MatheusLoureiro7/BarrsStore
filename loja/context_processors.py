from django.conf import settings


def marketing_tags(request):
    return {
        'google_analytics_id': getattr(settings, 'GOOGLE_ANALYTICS_ID', ''),
        'google_site_verification': getattr(settings, 'GOOGLE_SITE_VERIFICATION', ''),
        'meta_pixel_id': getattr(settings, 'META_PIXEL_ID', '') or '1413794504078637',
        'lead_nome': request.session.get('lead_nome', ''),
        'lead_telefone': request.session.get('lead_telefone', ''),
        'lead_capturado': request.session.get('lead_capturado', False),
        'turnstile_site_key': getattr(settings, 'TURNSTILE_SITE_KEY', ''),
        'turnstile_required': getattr(settings, 'TURNSTILE_REQUIRED', False),
        'csp_nonce': getattr(request, 'csp_nonce', ''),
    }
