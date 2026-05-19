from django import template


register = template.Library()


@register.filter
def cloudinary_url(image_or_url, transformation):
    """Aplica transformacoes Cloudinary preservando fallback para URLs normais."""
    if not image_or_url:
        return ''
    try:
        url = image_or_url.url
    except AttributeError:
        url = str(image_or_url)
    if 'res.cloudinary.com' not in url or '/upload/' not in url:
        return url
    return url.replace('/upload/', f'/upload/{transformation}/', 1)
