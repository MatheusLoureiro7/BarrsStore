import uuid

from django.db import migrations, models
from django.utils.text import slugify


def preencher_slugs_e_tokens(apps, schema_editor):
    Produto = apps.get_model('loja', 'Produto')
    Pedido = apps.get_model('loja', 'Pedido')

    slugs_usados = set()
    for produto in Produto.objects.all().order_by('id'):
        base_slug = slugify(produto.nome) or f'produto-{produto.id}'
        slug = base_slug
        contador = 2
        while slug in slugs_usados or Produto.objects.filter(slug=slug).exclude(id=produto.id).exists():
            slug = f'{base_slug}-{contador}'
            contador += 1
        produto.slug = slug
        slugs_usados.add(slug)
        produto.save(update_fields=['slug'])

    for pedido in Pedido.objects.filter(access_token__isnull=True):
        pedido.access_token = uuid.uuid4()
        pedido.save(update_fields=['access_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('loja', '0011_pedido_codigo_rastreio_pedido_email_rastreio_enviado_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='produto',
            name='slug',
            field=models.SlugField(blank=True, db_index=False, max_length=140, null=True),
        ),
        migrations.AddField(
            model_name='produto',
            name='meta_description',
            field=models.CharField(blank=True, default='', help_text='Resumo para Google, ate 160 caracteres', max_length=160),
        ),
        migrations.AddField(
            model_name='produto',
            name='imagem_alt',
            field=models.CharField(blank=True, default='', help_text='Texto alternativo da imagem para SEO e acessibilidade', max_length=120),
        ),
        migrations.AddField(
            model_name='pedido',
            name='access_token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='pedido',
            name='email_confirmacao_enviado',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(preencher_slugs_e_tokens, migrations.RunPython.noop),
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS loja_produto_slug_c2746fd3_like;',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name='produto',
            name='slug',
            field=models.SlugField(blank=True, max_length=140, unique=True),
        ),
        migrations.AlterField(
            model_name='pedido',
            name='access_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
