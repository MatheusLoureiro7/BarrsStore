from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0034_sprint5_forma_pagamento_index_observacoes_charfield'),
    ]

    operations = [
        migrations.AddField(
            model_name='cupom',
            name='so_clientes_fidelidade',
            field=models.BooleanField(default=False, help_text='Somente para clientes com pelo menos 1 pedido confirmado.'),
        ),
    ]
