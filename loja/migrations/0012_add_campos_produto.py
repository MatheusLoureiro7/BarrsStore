from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0011_pedido_codigo_rastreio_pedido_email_rastreio_enviado_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='produto',
            name='codigo_interno',
            field=models.CharField(blank=True, default='', help_text='Código interno (só visível no admin)', max_length=50),
        ),
        migrations.AddField(
            model_name='produto',
            name='estoque_proprio',
            field=models.BooleanField(default=True, help_text='Produto em estoque próprio? Se não, sob demanda.'),
        ),
    ]