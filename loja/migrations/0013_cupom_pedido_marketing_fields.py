from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0012_seo_security_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='Cupom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo', models.CharField(max_length=30, unique=True)),
                ('tipo', models.CharField(choices=[('percentual', 'Percentual'), ('valor', 'Valor fixo')], default='percentual', max_length=20)),
                ('valor', models.DecimalField(decimal_places=2, max_digits=10)),
                ('ativo', models.BooleanField(default=True)),
                ('uso_maximo', models.PositiveIntegerField(default=0, help_text='0 = sem limite')),
                ('usado', models.PositiveIntegerField(default=0)),
                ('valor_minimo', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Cupom',
                'verbose_name_plural': 'Cupons',
                'ordering': ['-criado_em'],
            },
        ),
        migrations.AddField(
            model_name='pedido',
            name='cupom_codigo',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
        migrations.AddField(
            model_name='pedido',
            name='desconto',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_pagamento_pendente_enviado',
            field=models.BooleanField(default=False),
        ),
    ]
