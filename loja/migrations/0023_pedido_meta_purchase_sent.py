# Generated manually for Meta Conversions API Purchase deduplication.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0022_marcar_estoque_baixado_pedidos_antigos'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='meta_purchase_sent',
            field=models.BooleanField(default=False),
        ),
    ]