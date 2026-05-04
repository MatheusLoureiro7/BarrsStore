from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0016_pedido_cpf'),
    ]

    operations = [
        migrations.AddField(
            model_name='produto',
            name='visivel',
            field=models.BooleanField(default=True, help_text='Exibir este produto no site?'),
        ),
    ]
