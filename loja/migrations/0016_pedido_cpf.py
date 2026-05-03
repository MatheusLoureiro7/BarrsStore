from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0015_carrinho_whatsapp_abandono'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='cpf',
            field=models.CharField(blank=True, default='', max_length=14),
        ),
    ]
