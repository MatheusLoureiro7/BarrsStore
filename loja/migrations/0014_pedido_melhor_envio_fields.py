from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0013_cupom_pedido_marketing_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='melhor_envio_service_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='pedido',
            name='melhor_envio_order_id',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='pedido',
            name='melhor_envio_status',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='pedido',
            name='melhor_envio_erro',
            field=models.TextField(blank=True, default=''),
        ),
    ]
