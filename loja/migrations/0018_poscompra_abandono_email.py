from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0017_produto_visivel'),
    ]

    operations = [
        # Carrinho: email capture + sequência de abandono
        migrations.AddField(
            model_name='carrinho',
            name='email_cliente',
            field=models.EmailField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='carrinho',
            name='email_abandono_1_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='carrinho',
            name='email_abandono_2_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='carrinho',
            name='email_abandono_3_enviado',
            field=models.BooleanField(default=False),
        ),
        # Pedido: sequência pós-compra
        migrations.AddField(
            model_name='pedido',
            name='email_poscompra_1_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_poscompra_2_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_poscompra_3_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_poscompra_4_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_poscompra_5_enviado',
            field=models.BooleanField(default=False),
        ),
    ]
