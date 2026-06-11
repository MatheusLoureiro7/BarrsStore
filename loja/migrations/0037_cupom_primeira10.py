from decimal import Decimal

from django.db import migrations


def criar_cupom_primeira10(apps, schema_editor):
    Cupom = apps.get_model('loja', 'Cupom')
    Cupom.objects.get_or_create(
        codigo='PRIMEIRA10',
        defaults={
            'tipo': 'percentual',
            'valor': Decimal('10.00'),
            'ativo': True,
            'uso_maximo': 0,
            'valor_minimo': Decimal('0.00'),
        },
    )


def remover_cupom_primeira10(apps, schema_editor):
    Cupom = apps.get_model('loja', 'Cupom')
    Cupom.objects.filter(codigo='PRIMEIRA10').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0036_lead_cupom_lead_usado_em_pedido_and_more'),
    ]

    operations = [
        migrations.RunPython(criar_cupom_primeira10, remover_cupom_primeira10),
    ]
