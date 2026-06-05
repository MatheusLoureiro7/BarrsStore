import hashlib
import hmac
import json
import time
from decimal import Decimal

from django.test import Client, TestCase, override_settings

from .mercadopago_security import (
    _parse_signature_header,
    _timestamp_fresco,
    validar_assinatura_mercadopago,
)
from .models import (
    Carrinho,
    Categoria,
    Cupom,
    ItemCarrinho,
    ItemPedido,
    Pedido,
    Produto,
    calcular_frete_por_estado,
)
from .validators import cpf_valido
from .views import baixar_estoque_pedido


class ProdutoSeoTests(TestCase):
    def test_seo_manual_tem_prioridade(self):
        produto = Produto.objects.create(
            nome='Colar Manual',
            preco=Decimal('89.90'),
            estoque=5,
            meta_description='Descrição manual premium para o Google.',
            imagem_alt='Alt manual da imagem do colar',
        )

        self.assertEqual(produto.get_seo_title(), 'Colar Manual | Barrs Store')
        self.assertEqual(produto.get_meta_description(), 'Descrição manual premium para o Google.')
        self.assertEqual(produto.get_image_alt(), 'Alt manual da imagem do colar')

    def test_save_preenche_campos_seo_vazios_no_admin(self):
        produto = Produto.objects.create(
            nome='Pulseira Automática',
            preco=Decimal('69.90'),
            estoque=5,
        )

        produto.refresh_from_db()
        self.assertIn('Pulseira Automática', produto.meta_description)
        self.assertLessEqual(len(produto.meta_description), 160)
        self.assertEqual(produto.imagem_alt, 'Pulseira Automática feminino da Barrs Store')

    def test_save_nao_sobrescreve_seo_manual(self):
        produto = Produto.objects.create(
            nome='Brinco Manual',
            preco=Decimal('49.90'),
            estoque=5,
            meta_description='Texto manual do produto.',
            imagem_alt='Alt manual do produto',
        )
        produto.nome = 'Brinco Manual Editado'
        produto.save()
        produto.refresh_from_db()

        self.assertEqual(produto.meta_description, 'Texto manual do produto.')
        self.assertEqual(produto.imagem_alt, 'Alt manual do produto')

    def test_seo_automatico_usa_nome_categoria_e_descricao(self):
        categoria = Categoria.objects.create(nome='Colares', slug='colar')
        produto = Produto.objects.create(
            nome='Colar Pérola',
            categoria=categoria,
            descricao='Peça delicada com brilho sofisticado para composições elegantes.',
            preco=Decimal('129.90'),
            estoque=3,
        )

        meta = produto.get_meta_description()
        self.assertEqual(produto.get_seo_title(), 'Colar Pérola | Barrs Store')
        self.assertIn('Colar Pérola', meta)
        self.assertTrue('colo' in meta or 'decotes' in meta or 'produções delicadas' in meta)
        self.assertLessEqual(len(meta), 160)
        self.assertEqual(produto.get_image_alt(), 'Colar Pérola feminino da Barrs Store')

    def test_meta_description_varia_por_categoria_sem_frases_repetitivas(self):
        categorias = [
            ('Colares', 'colar', 'Colar Coração Dourado'),
            ('Anéis', 'anel', 'Anel Pérola'),
            ('Pulseiras', 'pulseira', 'Pulseira Flor'),
            ('Brincos', 'brinco', 'Brinco Pedra Verde'),
            ('Riviera', 'riviera', 'Riviera Cristal'),
            ('Choker', 'choker', 'Choker Miçangas Azuis'),
        ]
        metas = []
        for nome_categoria, slug, nome_produto in categorias:
            categoria = Categoria.objects.create(nome=nome_categoria, slug=slug)
            produto = Produto.objects.create(
                nome=nome_produto,
                categoria=categoria,
                preco=Decimal('79.90'),
                estoque=4,
            )
            meta = produto.meta_description
            metas.append(meta)
            self.assertIn(nome_produto, meta)
            self.assertLessEqual(len(meta), 160)
            self.assertNotIn('semijoia elegante', meta.lower())
            self.assertNotIn('acabamento premium', meta.lower())
            self.assertNotIn('estilo versátil', meta.lower())

        self.assertEqual(len(set(metas)), len(metas))

    def test_schema_produto_sem_imagem_categoria_e_sem_estoque_nao_quebra(self):
        produto = Produto.objects.create(
            nome='Brinco Sem Estoque',
            preco=Decimal('59.90'),
            estoque=0,
        )

        schema = json.loads(produto.get_schema_json_ld(
            absolute_url='https://www.barrsstore.com.br/produto/brinco-sem-estoque/'
        ))

        self.assertEqual(schema['@type'], 'Product')
        self.assertEqual(schema['name'], 'Brinco Sem Estoque')
        self.assertNotIn('image', schema)
        self.assertEqual(schema['offers']['price'], '59.90')
        self.assertEqual(schema['offers']['priceCurrency'], 'BRL')
        self.assertEqual(schema['offers']['availability'], 'https://schema.org/OutOfStock')

    @override_settings(SITE_URL='https://www.barrsstore.com.br')
    def test_pagina_produto_renderiza_meta_og_alt_e_json_ld(self):
        produto = Produto.objects.create(
            nome='Anel SEO',
            descricao='Anel delicado com acabamento premium.',
            preco=Decimal('79.90'),
            estoque=4,
            imagem='produtos/anel-seo.jpg',
        )

        response = Client().get(produto.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<title>Anel SEO | Barrs Store</title>', html=False)
        self.assertContains(response, '<meta property="og:type" content="product">', html=False)
        self.assertContains(response, 'alt="Anel SEO feminino da Barrs Store"', html=False)
        self.assertContains(response, '"@type": "Product"', html=False)
        self.assertContains(response, '"availability": "https://schema.org/InStock"', html=False)


class HomeOrderingTests(TestCase):
    def test_produto_destacado_aparece_antes_do_mais_recente(self):
        destaque = Produto.objects.create(
            nome='Colar Destaque',
            preco=Decimal('89.90'),
            estoque=5,
            destaque=True,
        )
        comum = Produto.objects.create(
            nome='Brinco Recente',
            preco=Decimal('39.90'),
            estoque=5,
            destaque=False,
        )

        response = Client().get('/')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index(destaque.nome), html.index(comum.nome))

    def test_produto_destacado_continua_primeiro_com_ordem_menor_preco(self):
        destaque = Produto.objects.create(
            nome='Colar Destaque Caro',
            preco=Decimal('199.90'),
            estoque=5,
            destaque=True,
        )
        comum = Produto.objects.create(
            nome='Brinco Barato',
            preco=Decimal('19.90'),
            estoque=5,
            destaque=False,
        )

        response = Client().get('/?ordem=menor')
        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertLess(html.index(destaque.nome), html.index(comum.nome))


class ValidadorCPFTests(TestCase):
    def test_cpf_valido_com_mascara(self):
        self.assertTrue(cpf_valido('529.982.247-25'))

    def test_cpf_valido_sem_mascara(self):
        self.assertTrue(cpf_valido('52998224725'))

    def test_cpf_invalido_repetido(self):
        self.assertFalse(cpf_valido('111.111.111-11'))

    def test_cpf_invalido_dv_errado(self):
        self.assertFalse(cpf_valido('529.982.247-26'))

    def test_cpf_vazio_ou_none(self):
        self.assertFalse(cpf_valido(''))
        self.assertFalse(cpf_valido(None))


class CupomTests(TestCase):
    def test_cupom_percentual_calcula_desconto(self):
        cupom = Cupom.objects.create(codigo='BARRS10', tipo='percentual', valor=10)
        self.assertEqual(cupom.calcular_desconto(Decimal('100')), Decimal('10.00'))

    def test_cupom_valor_fixo_calcula_desconto(self):
        cupom = Cupom.objects.create(codigo='BARRS20', tipo='valor', valor=Decimal('20'))
        self.assertEqual(cupom.calcular_desconto(Decimal('100')), Decimal('20.00'))

    def test_cupom_valor_fixo_nao_excede_subtotal(self):
        cupom = Cupom.objects.create(codigo='BARRS999', tipo='valor', valor=Decimal('999'))
        self.assertEqual(cupom.calcular_desconto(Decimal('50')), Decimal('50'))

    def test_cupom_frete_gratis_retorna_valor_do_frete(self):
        cupom = Cupom.objects.create(codigo='FRETEZERO', tipo='frete_gratis', valor=0)
        self.assertEqual(
            cupom.calcular_desconto(Decimal('100'), frete=Decimal('15.90')),
            Decimal('15.90'),
        )

    def test_cupom_inativo_invalido(self):
        cupom = Cupom.objects.create(codigo='OFF', tipo='percentual', valor=10, ativo=False)
        valido, _motivo = cupom.valido_para(Decimal('100'))
        self.assertFalse(valido)

    def test_cupom_esgotado_invalido(self):
        cupom = Cupom.objects.create(
            codigo='LIMIT', tipo='percentual', valor=10, uso_maximo=1, usado=1,
        )
        valido, _motivo = cupom.valido_para(Decimal('100'))
        self.assertFalse(valido)

    def test_cupom_abaixo_do_minimo_invalido(self):
        cupom = Cupom.objects.create(
            codigo='MIN', tipo='percentual', valor=10, valor_minimo=Decimal('150'),
        )
        valido, _motivo = cupom.valido_para(Decimal('100'))
        self.assertFalse(valido)

    def test_cupom_valido_acima_do_minimo(self):
        cupom = Cupom.objects.create(
            codigo='OK', tipo='percentual', valor=10, valor_minimo=Decimal('50'),
        )
        valido, _motivo = cupom.valido_para(Decimal('100'))
        self.assertTrue(valido)


class CalcularFreteTests(TestCase):
    def test_sp_subtotal_baixo_cobra_frete(self):
        frete, _minimo = calcular_frete_por_estado('SP', Decimal('30'))
        self.assertEqual(frete, Decimal('9.90'))

    def test_sp_subtotal_atinge_gratis(self):
        frete, _minimo = calcular_frete_por_estado('SP', Decimal('79'))
        self.assertEqual(frete, Decimal('0'))

    def test_norte_am_cobra_frete_norte(self):
        frete, _minimo = calcular_frete_por_estado('AM', Decimal('100'))
        self.assertEqual(frete, Decimal('21.90'))

    def test_norte_atinge_gratis(self):
        frete, _minimo = calcular_frete_por_estado('AC', Decimal('149'))
        self.assertEqual(frete, Decimal('0'))

    def test_brasil_padrao_cobra_frete_brasil(self):
        frete, _minimo = calcular_frete_por_estado('RJ', Decimal('80'))
        self.assertEqual(frete, Decimal('16.90'))

    def test_brasil_atinge_gratis(self):
        frete, _minimo = calcular_frete_por_estado('MG', Decimal('119'))
        self.assertEqual(frete, Decimal('0'))

    def test_estado_vazio_trata_como_brasil(self):
        frete, _minimo = calcular_frete_por_estado('', Decimal('80'))
        self.assertEqual(frete, Decimal('16.90'))

    def test_estado_lowercase_normalizado(self):
        frete, _minimo = calcular_frete_por_estado('sp', Decimal('30'))
        self.assertEqual(frete, Decimal('9.90'))


class MercadoPagoSignatureParseTests(TestCase):
    def test_parse_signature_valido(self):
        ts, v1 = _parse_signature_header('ts=1234567890,v1=abc123')
        self.assertEqual(ts, '1234567890')
        self.assertEqual(v1, 'abc123')

    def test_parse_signature_com_espacos(self):
        ts, v1 = _parse_signature_header(' ts = 1234 , v1 = xyz ')
        self.assertEqual(ts, '1234')
        self.assertEqual(v1, 'xyz')

    def test_parse_signature_vazio(self):
        ts, v1 = _parse_signature_header('')
        self.assertIsNone(ts)
        self.assertIsNone(v1)

    def test_parse_signature_none(self):
        ts, v1 = _parse_signature_header(None)
        self.assertIsNone(ts)
        self.assertIsNone(v1)

    def test_parse_signature_ignora_partes_invalidas(self):
        ts, v1 = _parse_signature_header('foo,ts=1,bar=baz,v1=ok')
        self.assertEqual(ts, '1')
        self.assertEqual(v1, 'ok')


class MercadoPagoTimestampFrescoTests(TestCase):
    def test_timestamp_recente_em_ms(self):
        agora_ms = int(time.time() * 1000)
        self.assertTrue(_timestamp_fresco(str(agora_ms)))

    def test_timestamp_recente_em_segundos(self):
        # Fallback para integracoes que enviam ts em segundos.
        agora_s = int(time.time())
        self.assertTrue(_timestamp_fresco(str(agora_s)))

    def test_timestamp_antigo_alem_tolerancia(self):
        antigo_ms = (int(time.time()) - 7200) * 1000  # 2h atras, tolerancia padrao 600s
        self.assertFalse(_timestamp_fresco(str(antigo_ms)))

    def test_timestamp_invalido_retorna_false(self):
        self.assertFalse(_timestamp_fresco('nao-e-numero'))
        self.assertFalse(_timestamp_fresco(None))


class CheckoutTests(TestCase):
    def test_checkout_bloqueia_cpf_invalido(self):
        produto = Produto.objects.create(nome='Produto Teste', preco=1, estoque=5)
        carrinho = Carrinho.objects.create()
        ItemCarrinho.objects.create(carrinho=carrinho, produto=produto, quantidade=1)

        client = Client()
        session = client.session
        session['carrinho_id'] = carrinho.id
        session.save()

        response = client.post('/finalizar/', {
            'nome': 'Cliente Teste',
            'email': 'cliente@example.com',
            'telefone': '11999999999',
            'cpf': '111.111.111-11',
            'senha': 'SenhaForte123',
            'cep': '01001000',
            'rua': 'Rua Teste',
            'numero': '123',
            'bairro': 'Centro',
            'cidade': 'Sao Paulo',
            'estado': 'SP',
            'frete_valor': '10.00',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Informe um CPF valido.')


class MercadoPagoWebhookSecurityTests(TestCase):
    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='segredo-teste')
    def test_assinatura_mercadopago_valida(self):
        ts = str(int(time.time() * 1000))
        request_id = 'req-123'
        data_id = '123456'
        manifesto = f'id:{data_id};request-id:{request_id};ts:{ts};'
        assinatura = hmac.new(b'segredo-teste', manifesto.encode('utf-8'), hashlib.sha256).hexdigest()

        request = Client().post(
            f'/pagamento/webhook/?data.id={data_id}&type=payment',
            data={'data': {'id': data_id}, 'type': 'payment'},
            content_type='application/json',
            HTTP_X_REQUEST_ID=request_id,
            HTTP_X_SIGNATURE=f'ts={ts},v1={assinatura}',
        ).wsgi_request

        valido, motivo = validar_assinatura_mercadopago(request, {'data': {'id': data_id}})
        self.assertTrue(valido, motivo)

    @override_settings(MERCADOPAGO_WEBHOOK_SECRET='segredo-teste')
    def test_assinatura_mercadopago_invalida(self):
        ts = str(int(time.time() * 1000))
        request = Client().post(
            '/pagamento/webhook/?data.id=999&type=payment',
            data={'data': {'id': '999'}, 'type': 'payment'},
            content_type='application/json',
            HTTP_X_REQUEST_ID='req-fake',
            HTTP_X_SIGNATURE=f'ts={ts},v1=deadbeef',
        ).wsgi_request

        valido, motivo = validar_assinatura_mercadopago(request, {'data': {'id': '999'}})
        self.assertFalse(valido)
        self.assertEqual(motivo, 'assinatura_invalida')


class BaixaEstoqueIdempotenciaTests(TestCase):
    def test_baixar_estoque_pedido_chamado_duas_vezes_baixa_uma_so(self):
        produto = Produto.objects.create(nome='Anel Idem', preco=Decimal('100'), estoque=10)
        pedido = Pedido.objects.create(
            nome='Cliente',
            email='a@b.com',
            cep='01001000',
            rua='Rua',
            numero='1',
            bairro='Centro',
            cidade='SP',
            estado='SP',
            forma_pagamento='pix',
            subtotal=Decimal('100'),
            total=Decimal('100'),
        )
        ItemPedido.objects.create(
            pedido=pedido,
            produto=produto,
            nome_produto=produto.nome,
            quantidade=2,
            preco_unitario=Decimal('100'),
        )

        primeira = baixar_estoque_pedido(pedido)
        segunda = baixar_estoque_pedido(pedido)

        produto.refresh_from_db()
        pedido.refresh_from_db()

        self.assertTrue(primeira)
        self.assertFalse(segunda)
        self.assertEqual(produto.estoque, 8)
        self.assertTrue(pedido.estoque_baixado)


class CaptureUtmMiddlewareTests(TestCase):
    def test_utm_acumula_e_persiste_na_sessao(self):
        client = Client()
        # Primeira visita: vem com utm_source + utm_medium.
        client.get('/?utm_source=instagram&utm_medium=stories')
        session = client.session
        self.assertEqual(session['utm']['utm_source'], 'instagram')
        self.assertEqual(session['utm']['utm_medium'], 'stories')

        # Segunda visita: vem com fbclid; mantém utm_source anterior.
        client.get('/?fbclid=ABC123')
        session = client.session
        self.assertEqual(session['utm']['fbclid'], 'ABC123')
        self.assertEqual(session['utm']['utm_source'], 'instagram')

        # Terceira visita com novo utm_source: last-touch sobrescreve.
        client.get('/?utm_source=google&utm_campaign=blackfriday')
        session = client.session
        self.assertEqual(session['utm']['utm_source'], 'google')
        self.assertEqual(session['utm']['utm_campaign'], 'blackfriday')
        self.assertEqual(session['utm']['fbclid'], 'ABC123')  # mantém

    def test_visita_sem_utm_nao_quebra_sessao(self):
        client = Client()
        resp = client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('utm', client.session)


class InterpretarErroMPTests(TestCase):
    def test_status_500_internal_error_e_transient(self):
        from .views import interpretar_erro_mp
        info = interpretar_erro_mp(500, {'message': 'internal_error', 'status_detail': None, 'cause': []})
        self.assertEqual(info['categoria'], 'transient')
        self.assertTrue(info['pode_tentar'])
        self.assertIn('Instabilidade', info['mensagem'])

    def test_cvv_invalido_aponta_para_cartao(self):
        from .views import interpretar_erro_mp
        info = interpretar_erro_mp(400, {'status_detail': 'cc_rejected_bad_filled_security_code'})
        self.assertEqual(info['categoria'], 'cartao')
        self.assertTrue(info['pode_tentar'])
        self.assertIn('CVV', info['sugestao'])

    def test_saldo_insuficiente_sugere_outro_metodo(self):
        from .views import interpretar_erro_mp
        info = interpretar_erro_mp(400, {'status_detail': 'cc_rejected_insufficient_amount'})
        self.assertEqual(info['categoria'], 'banco')
        self.assertFalse(info['pode_tentar'])
        self.assertIn('Pix', info['sugestao'])

    def test_status_detail_desconhecido_cai_no_generico(self):
        from .views import interpretar_erro_mp
        info = interpretar_erro_mp(400, {'status_detail': 'algo_inesperado'})
        self.assertEqual(info['categoria'], 'banco')


class CarrinhoAuthorizationTests(TestCase):
    def test_remover_item_de_carrinho_alheio_retorna_404(self):
        produto = Produto.objects.create(nome='Anel Auth', preco=Decimal('50'), estoque=5)
        carrinho_vitima = Carrinho.objects.create()
        item_vitima = ItemCarrinho.objects.create(
            carrinho=carrinho_vitima, produto=produto, quantidade=2,
        )

        # Atacante tem sessao com OUTRO carrinho.
        carrinho_atacante = Carrinho.objects.create()
        client = Client()
        session = client.session
        session['carrinho_id'] = carrinho_atacante.id
        session.save()

        response = client.post(f'/remover/{item_vitima.id}/')
        self.assertEqual(response.status_code, 404)
        item_vitima.refresh_from_db()
        self.assertEqual(item_vitima.quantidade, 2)  # nao mexeu

        response = client.post(f'/deletar/{item_vitima.id}/')
        self.assertEqual(response.status_code, 404)
        self.assertTrue(ItemCarrinho.objects.filter(id=item_vitima.id).exists())


# ── TESTES DO SIGNAL DE WEBHOOK ───────────────────────────────────
import logging
from unittest.mock import patch


def _criar_pedido_site(status='pendente'):
    return Pedido.objects.create(
        nome='Test',
        email='t@test.com',
        telefone='',
        cpf='',
        cep='01310-100',
        rua='Av Paulista',
        numero='1',
        bairro='Bela Vista',
        cidade='SP',
        estado='SP',
        forma_pagamento='pix',
        status=status,
        total=Decimal('100'),
    )


class WebhookSignalTests(TestCase):
    @patch('loja.signals._chamar_webhook_erp')
    def test_dispara_ao_confirmar(self, mock_chamar):
        ped = _criar_pedido_site('pendente')
        ped.status = 'confirmado'
        ped.save(update_fields=['status'])
        mock_chamar.assert_called_once_with(ped.id)

    @patch('loja.signals._chamar_webhook_erp')
    def test_nao_dispara_sem_status_no_update_fields(self, mock_chamar):
        ped = _criar_pedido_site('pendente')
        ped.nome = 'Outro'
        ped.save(update_fields=['nome'])
        mock_chamar.assert_not_called()

    @patch('loja.signals._chamar_webhook_erp')
    def test_nao_dispara_na_criacao(self, mock_chamar):
        _criar_pedido_site('confirmado')
        mock_chamar.assert_not_called()

    @patch('loja.signals._chamar_webhook_erp')
    def test_nao_dispara_para_outros_status(self, mock_chamar):
        ped = _criar_pedido_site('pendente')
        ped.status = 'enviado'
        ped.save(update_fields=['status'])
        mock_chamar.assert_not_called()

    @override_settings(
        ERP_WEBHOOK_URL='http://erp.test/webhook/nova-venda/',
        ERP_WEBHOOK_TOKEN='tok123',
    )
    @patch('loja.signals.requests.post')
    def test_chamar_webhook_faz_post_correto(self, mock_post):
        from loja.signals import _chamar_webhook_erp
        _chamar_webhook_erp(42)
        mock_post.assert_called_once_with(
            'http://erp.test/webhook/nova-venda/',
            json={'pedido_id': 42},
            headers={'X-Webhook-Token': 'tok123'},
            timeout=5,
        )

    @override_settings(ERP_WEBHOOK_URL='', ERP_WEBHOOK_TOKEN='')
    @patch('loja.signals.requests.post')
    def test_sem_url_nao_faz_post(self, mock_post):
        from loja.signals import _chamar_webhook_erp
        _chamar_webhook_erp(42)
        mock_post.assert_not_called()

    @override_settings(
        ERP_WEBHOOK_URL='http://erp.test/',
        ERP_WEBHOOK_TOKEN='tok',
    )
    @patch('loja.signals.requests.post', side_effect=Exception('timeout'))
    def test_falha_silenciosa(self, mock_post):
        from loja.signals import _chamar_webhook_erp
        # não deve levantar exceção
        _chamar_webhook_erp(42)
