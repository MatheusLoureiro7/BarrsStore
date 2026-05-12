import re
from django import template

register = template.Library()


@register.filter
def telefone_br(value):
    """Formata telefone brasileiro para exibicao: (11) 11111-1111."""
    if not value:
        return ''

    digits = re.sub(r'\D', '', str(value))
    if digits.startswith('55') and len(digits) in (12, 13):
        digits = digits[2:]

    if len(digits) == 11:
        return f'({digits[:2]}) {digits[2:7]}-{digits[7:]}'
    if len(digits) == 10:
        return f'({digits[:2]}) {digits[2:6]}-{digits[6:]}'

    return str(value)