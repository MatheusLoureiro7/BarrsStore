import hashlib
import hmac
import time

from django.test import Client, TestCase, override_settings

from .mercadopago_security import validar_assinatura_mercadopago
from .models import Carrinho, Cupom, ItemCarrinho, Produto
from .validators import cpf_valido


class ValidadorCPFTests(TestCase):
    def test_cpf_valido_com_mascara(self):
        self.assertTrue(cpf_valido('529.982.247-25'))

    def test_cpf_invalido_repetido(self):
        self.assertFalse(cpf_valido('111.111.111-11'))


class CupomTests(TestCase):
    def test_cupom_percentual_calcula_desconto(self):
        cupom = Cupom.objects.create(codigo='BARRS10', tipo='percentual', valor=10)
        self.assertEqual(cupom.calcular_desconto(100), 10)


class CheckoutTests(TestCase):
    def test_checkout_bloqueia_cpf_invalido(self):
        produto = Produto.objects.create(nome='Produto Teste', preco=1, estoque=5)
        carrinho = Carrinho.objects.create()
        ItemCarrinho.objects.create(carrinho=carrinho, produto=produto, quantidade=1)

        client = Client(HTTP_HOST='www.barrsstore.com.br')
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
