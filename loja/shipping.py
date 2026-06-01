from decimal import Decimal

FRETE_SP = Decimal('9.90')
FRETE_GRATIS_SP = Decimal('79.00')
FRETE_NORTE = Decimal('21.90')
FRETE_GRATIS_NORTE = Decimal('149.00')
FRETE_BRASIL = Decimal('16.90')
FRETE_GRATIS_BRASIL = Decimal('119.00')
ESTADOS_NORTE = ['AM', 'RR', 'AC', 'AP', 'PA', 'TO', 'RO']


def calcular_frete_por_estado(estado, subtotal):
    estado = (estado or '').upper().strip()
    if estado == 'SP':
        valor = FRETE_SP
        minimo = FRETE_GRATIS_SP
    elif estado in ESTADOS_NORTE:
        valor = FRETE_NORTE
        minimo = FRETE_GRATIS_NORTE
    else:
        valor = FRETE_BRASIL
        minimo = FRETE_GRATIS_BRASIL
    frete = Decimal('0') if subtotal >= minimo else valor
    return frete, minimo
