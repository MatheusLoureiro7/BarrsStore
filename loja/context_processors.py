from django.conf import settings


def marketing_tags(request):
    return {
        'google_analytics_id': getattr(settings, 'GOOGLE_ANALYTICS_ID', ''),
        'google_site_verification': getattr(settings, 'GOOGLE_SITE_VERIFICATION', ''),
        'lead_nome': request.session.get('lead_nome', ''),
        'lead_telefone': request.session.get('lead_telefone', ''),
        'lead_capturado': request.session.get('lead_capturado', False),
    }
