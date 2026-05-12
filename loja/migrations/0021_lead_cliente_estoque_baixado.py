from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0020_produto_cliques'),
    ]

    operations = [
        migrations.AddField(
            model_name='carrinho',
            name='nome_cliente',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='pedido',
            name='estoque_baixado',
            field=models.BooleanField(default=False),
        ),
    ]
