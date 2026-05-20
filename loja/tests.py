import hashlib
import hmac
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
    Cupom,
    ItemCarrinho,
    ItemPedido,
    Pedido,
    Produto,
    calcular_frete_por_estado,
)
from .validators import cpf_valido
from .views import baixar_estoque_pedido


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
