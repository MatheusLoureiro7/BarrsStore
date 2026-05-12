from django.db import migrations


def marcar_pedidos_antigos(apps, schema_editor):
    Pedido = apps.get_model('loja', 'Pedido')
    Pedido.objects.filter(status__in=['confirmado', 'enviado', 'entregue']).update(estoque_baixado=True)


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0021_lead_cliente_estoque_baixado'),
    ]

    operations = [
        migrations.RunPython(marcar_pedidos_antigos, migrations.RunPython.noop),
    ]
