# Lalamove v3 — Integração de Frete Motoboy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar cotação de frete motoboy via Lalamove v3 para CEPs de São Paulo como primeira opção no calculador de frete existente, sem alterar URLs, CSS ou a estrutura geral dos templates.

**Architecture:** Backend aggregation no `calcular_frete_melhor_envio` existente em `loja/views/shipping.py`. Quando o CEP é de SP, o endpoint chama `loja/integrations/lalamove.py` (novo arquivo) após obter as opções do Melhor Envio e insere o resultado no topo de `opcoes`. Falhas do Lalamove são silenciosas. Dois templates recebem correção mínima de 1 linha para exibir "Entrega hoje" em vez de "até 0 dias úteis".

**Tech Stack:** Python 3.13, Django 6.0, requests 2.33, hmac/hashlib (stdlib), Django cache framework (Redis/LocMem já configurados), ViaCEP API (gratuita), Nominatim/OpenStreetMap (gratuito, sem chave).

---

## File Map

| Ação | Arquivo | O que muda |
|---|---|---|
| Modificar | `barrs_store/settings.py` | +6 variáveis de ambiente Lalamove |
| Modificar | `.env.example` | +6 entradas documentadas |
| Criar | `loja/integrations/lalamove.py` | 3 funções: `is_sao_paulo_cep`, `cep_to_coordinates`, `get_lalamove_quotation` |
| Modificar | `loja/tests.py` | Testes das 3 funções + integração da view |
| Modificar | `loja/views/shipping.py` | Import das funções + bloco Lalamove antes do `return JsonResponse` |
| Modificar | `loja/templates/detalhe.html` | 1 linha JS: renderização de `prazo === 0` |
| Modificar | `loja/templates/carrinho.html` | 1 linha JS: renderização de `prazo === 0` |

---

### Task 1: Settings e variáveis de ambiente

**Files:**
- Modify: `barrs_store/settings.py`
- Modify: `.env.example`

- [ ] **Step 1: Adicionar variáveis ao `settings.py`**

Em `barrs_store/settings.py`, localize a linha `ERP_WEBHOOK_TOKEN = os.environ.get('ERP_WEBHOOK_TOKEN', '')` e adicione logo após:

```python
LALAMOVE_API_KEY        = os.environ.get('LALAMOVE_API_KEY', '')
LALAMOVE_API_SECRET     = os.environ.get('LALAMOVE_API_SECRET', '')
LALAMOVE_SANDBOX        = os.environ.get('LALAMOVE_SANDBOX', 'True') == 'True'
LALAMOVE_ORIGIN_LAT     = os.environ.get('LALAMOVE_ORIGIN_LAT', '')
LALAMOVE_ORIGIN_LNG     = os.environ.get('LALAMOVE_ORIGIN_LNG', '')
LALAMOVE_ORIGIN_ADDRESS = os.environ.get('LALAMOVE_ORIGIN_ADDRESS', '')
```

- [ ] **Step 2: Adicionar entradas ao `.env.example`**

Adicione ao final de `.env.example`:

```
# Lalamove — frete motoboy para CEPs de SP
LALAMOVE_API_KEY=
LALAMOVE_API_SECRET=
LALAMOVE_SANDBOX=True
LALAMOVE_ORIGIN_LAT=
LALAMOVE_ORIGIN_LNG=
LALAMOVE_ORIGIN_ADDRESS=
```

- [ ] **Step 3: Verificar que o projeto sobe sem erros**

```bash
python manage.py check
```

Esperado: `System check identified no issues (0 silenced).`

- [ ] **Step 4: Commit**

```bash
git add barrs_store/settings.py .env.example
git commit -m "feat: add Lalamove env vars to settings"
```

---

### Task 2: `is_sao_paulo_cep` — detecção de CEP de SP

**Files:**
- Create: `loja/integrations/lalamove.py`
- Modify: `loja/tests.py`

- [ ] **Step 1: Escrever os testes**

Adicione ao final de `loja/tests.py`:

```python
from loja.integrations.lalamove import is_sao_paulo_cep


class IsSaoPauloCepTests(TestCase):
    def test_range_baixo_sp(self):
        self.assertTrue(is_sao_paulo_cep('01310100'))   # Av. Paulista

    def test_range_baixo_sp_com_hifen(self):
        self.assertTrue(is_sao_paulo_cep('01310-100'))

    def test_limite_inferior_range_baixo(self):
        self.assertTrue(is_sao_paulo_cep('01000000'))

    def test_limite_superior_range_baixo(self):
        self.assertTrue(is_sao_paulo_cep('05999999'))

    def test_range_alto_sp(self):
        self.assertTrue(is_sao_paulo_cep('08250000'))

    def test_limite_superior_range_alto(self):
        self.assertTrue(is_sao_paulo_cep('08499999'))

    def test_entre_os_dois_ranges_nao_e_sp(self):
        self.assertFalse(is_sao_paulo_cep('06000000'))  # Osasco/Grande SP, não SP capital

    def test_acima_dos_ranges_nao_e_sp(self):
        self.assertFalse(is_sao_paulo_cep('08500000'))

    def test_rio_de_janeiro_nao_e_sp(self):
        self.assertFalse(is_sao_paulo_cep('20040020'))

    def test_cep_invalido_7_digitos(self):
        self.assertFalse(is_sao_paulo_cep('0131010'))

    def test_cep_vazio(self):
        self.assertFalse(is_sao_paulo_cep(''))

    def test_cep_com_letras(self):
        self.assertFalse(is_sao_paulo_cep('0131010X'))
```

- [ ] **Step 2: Executar os testes para confirmar que falham**

```bash
python manage.py test loja.tests.IsSaoPauloCepTests
```

Esperado: `ImportError: cannot import name 'is_sao_paulo_cep' from 'loja.integrations.lalamove'`

- [ ] **Step 3: Criar `loja/integrations/lalamove.py`**

```python
import hashlib
import hmac as hmac_lib
import json
import logging
import time

import requests as http_requests
from django.core.cache import cache

logger = logging.getLogger(__name__)


def is_sao_paulo_cep(cep: str) -> bool:
    cep = cep.replace('-', '').replace(' ', '')
    if len(cep) != 8 or not cep.isdigit():
        return False
    n = int(cep)
    return (1_000_000 <= n <= 5_999_999) or (8_000_000 <= n <= 8_499_999)
```

- [ ] **Step 4: Executar os testes para confirmar que passam**

```bash
python manage.py test loja.tests.IsSaoPauloCepTests
```

Esperado: `Ran 12 tests in 0.001s  OK`

- [ ] **Step 5: Commit**

```bash
git add loja/integrations/lalamove.py loja/tests.py
git commit -m "feat: add is_sao_paulo_cep to lalamove integration"
```

---

### Task 3: `cep_to_coordinates` — geocoding via ViaCEP + Nominatim

**Files:**
- Modify: `loja/integrations/lalamove.py`
- Modify: `loja/tests.py`

- [ ] **Step 1: Escrever os testes**

Adicione ao final de `loja/tests.py` (após `IsSaoPauloCepTests`):

```python
from unittest.mock import Mock, patch

from loja.integrations.lalamove import cep_to_coordinates


class CepToCoordinatesTests(TestCase):
    @patch('loja.integrations.lalamove.http_requests.get')
    def test_retorna_coordenadas(self, mock_get):
        mock_viacep = Mock()
        mock_viacep.raise_for_status = Mock()
        mock_viacep.json.return_value = {
            'logradouro': 'Avenida Paulista',
            'bairro': 'Bela Vista',
            'localidade': 'São Paulo',
            'uf': 'SP',
        }
        mock_nom = Mock()
        mock_nom.raise_for_status = Mock()
        mock_nom.json.return_value = [{'lat': '-23.5614', 'lon': '-46.6564'}]
        mock_get.side_effect = [mock_viacep, mock_nom]

        result = cep_to_coordinates('01310100')

        self.assertEqual(result['lat'], '-23.5614')
        self.assertEqual(result['lng'], '-46.6564')
        self.assertIn('São Paulo', result['address'])
        self.assertEqual(result['cep'], '01310100')

    @patch('loja.integrations.lalamove.http_requests.get')
    def test_levanta_runtime_error_cep_nao_encontrado(self, mock_get):
        mock_viacep = Mock()
        mock_viacep.raise_for_status = Mock()
        mock_viacep.json.return_value = {'erro': True}
        mock_get.return_value = mock_viacep

        with self.assertRaises(RuntimeError):
            cep_to_coordinates('00000000')

    @patch('loja.integrations.lalamove.http_requests.get')
    def test_levanta_runtime_error_nominatim_vazio(self, mock_get):
        mock_viacep = Mock()
        mock_viacep.raise_for_status = Mock()
        mock_viacep.json.return_value = {
            'logradouro': 'Rua X', 'bairro': 'Y',
            'localidade': 'São Paulo', 'uf': 'SP',
        }
        mock_nom = Mock()
        mock_nom.raise_for_status = Mock()
        mock_nom.json.return_value = []
        mock_get.side_effect = [mock_viacep, mock_nom]

        with self.assertRaises(RuntimeError):
            cep_to_coordinates('01310100')
```

- [ ] **Step 2: Executar os testes para confirmar que falham**

```bash
python manage.py test loja.tests.CepToCoordinatesTests
```

Esperado: `ImportError: cannot import name 'cep_to_coordinates'`

- [ ] **Step 3: Adicionar `cep_to_coordinates` ao `loja/integrations/lalamove.py`**

Adicione após `is_sao_paulo_cep`:

```python
def cep_to_coordinates(cep: str) -> dict:
    cache_key = f'lalamove:coords:{cep}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    via_resp = http_requests.get(
        f'https://viacep.com.br/ws/{cep}/json/',
        timeout=5,
        headers={'User-Agent': 'BarrsStore contato.barrsstore@gmail.com'},
    )
    via_resp.raise_for_status()
    via_data = via_resp.json()

    if via_data.get('erro'):
        raise RuntimeError(f'CEP {cep} não encontrado no ViaCEP.')

    partes = [
        via_data.get('logradouro', ''),
        via_data.get('bairro', ''),
        via_data.get('localidade', ''),
        via_data.get('uf', ''),
        'Brasil',
    ]
    address = ', '.join(p for p in partes if p)

    nom_resp = http_requests.get(
        'https://nominatim.openstreetmap.org/search',
        params={'q': address, 'format': 'json', 'limit': 1, 'countrycodes': 'br'},
        timeout=8,
        headers={'User-Agent': 'BarrsStore contato.barrsstore@gmail.com'},
    )
    nom_resp.raise_for_status()
    nom_data = nom_resp.json()

    if not nom_data:
        raise RuntimeError(f'Não foi possível geocodificar o CEP {cep}.')

    result = {
        'lat': nom_data[0]['lat'],
        'lng': nom_data[0]['lon'],   # Nominatim usa 'lon'; Lalamove espera 'lng'
        'address': address,
        'cep': cep,
    }
    cache.set(cache_key, result, 3600)
    return result
```

- [ ] **Step 4: Executar os testes para confirmar que passam**

```bash
python manage.py test loja.tests.CepToCoordinatesTests
```

Esperado: `Ran 3 tests in 0.003s  OK`

- [ ] **Step 5: Commit**

```bash
git add loja/integrations/lalamove.py loja/tests.py
git commit -m "feat: add cep_to_coordinates with ViaCEP + Nominatim geocoding"
```

---

### Task 4: `get_lalamove_quotation` — cotação via API Lalamove v3

**Files:**
- Modify: `loja/integrations/lalamove.py`
- Modify: `loja/tests.py`

- [ ] **Step 1: Escrever os testes**

Adicione ao final de `loja/tests.py`:

```python
from loja.integrations.lalamove import get_lalamove_quotation


class GetLalamoveQuotationTests(TestCase):
    def setUp(self):
        self.origin = {
            'lat': '-23.541', 'lng': '-46.638',
            'address': 'Rua Equestre 170, Fazenda Aricanduva, São Paulo, SP, Brasil',
            'cep': '08275700',
        }
        self.dest = {
            'lat': '-23.561', 'lng': '-46.656',
            'address': 'Avenida Paulista, Bela Vista, São Paulo, SP, Brasil',
            'cep': '01310100',
        }

    @override_settings(
        LALAMOVE_API_KEY='test_key',
        LALAMOVE_API_SECRET='test_secret',
        LALAMOVE_SANDBOX=True,
    )
    @patch('loja.integrations.lalamove.http_requests.post')
    def test_retorna_preco_e_quotation_id(self, mock_post):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'data': {
                'quotationId': 'QT-TEST-123',
                'priceBreakdown': {'total': '18.50'},
            }
        }
        mock_post.return_value = mock_resp

        result = get_lalamove_quotation(self.origin, self.dest)

        self.assertAlmostEqual(result['price'], 18.50)
        self.assertEqual(result['quotation_id'], 'QT-TEST-123')
        self.assertIn('eta', result)

    @override_settings(
        LALAMOVE_API_KEY='test_key',
        LALAMOVE_API_SECRET='test_secret',
        LALAMOVE_SANDBOX=True,
    )
    @patch('loja.integrations.lalamove.http_requests.post')
    def test_levanta_erro_em_resposta_4xx(self, mock_post):
        mock_resp = Mock()
        mock_resp.status_code = 400
        mock_resp.text = '{"message": "invalid stops"}'
        mock_post.return_value = mock_resp

        with self.assertRaises(RuntimeError):
            get_lalamove_quotation(self.origin, self.dest)

    @override_settings(LALAMOVE_API_KEY='', LALAMOVE_API_SECRET='')
    def test_levanta_erro_sem_configuracao(self):
        with self.assertRaises(RuntimeError):
            get_lalamove_quotation(self.origin, self.dest)

    @override_settings(
        LALAMOVE_API_KEY='test_key',
        LALAMOVE_API_SECRET='test_secret',
        LALAMOVE_SANDBOX=True,
    )
    @patch('loja.integrations.lalamove.http_requests.post')
    def test_cabecalho_authorization_e_market(self, mock_post):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'data': {'quotationId': 'QT-X', 'priceBreakdown': {'total': '10.00'}}
        }
        mock_post.return_value = mock_resp

        get_lalamove_quotation(self.origin, self.dest)

        _, kwargs = mock_post.call_args
        auth = kwargs['headers']['Authorization']
        self.assertTrue(auth.startswith('hmac test_key:'))
        self.assertEqual(kwargs['headers']['Market'], 'BR')
```

- [ ] **Step 2: Executar os testes para confirmar que falham**

```bash
python manage.py test loja.tests.GetLalamoveQuotationTests
```

Esperado: `ImportError: cannot import name 'get_lalamove_quotation'`

- [ ] **Step 3: Adicionar `get_lalamove_quotation` ao `loja/integrations/lalamove.py`**

Adicione após `cep_to_coordinates`:

```python
def get_lalamove_quotation(origin: dict, destination: dict) -> dict:
    from django.conf import settings as django_settings

    api_key = getattr(django_settings, 'LALAMOVE_API_KEY', '')
    api_secret = getattr(django_settings, 'LALAMOVE_API_SECRET', '')
    sandbox = getattr(django_settings, 'LALAMOVE_SANDBOX', True)

    if not api_key or not api_secret:
        raise RuntimeError('Lalamove não configurada: LALAMOVE_API_KEY ou LALAMOVE_API_SECRET ausentes.')

    cache_key = f'lalamove:quote:{destination["cep"]}'
    cached = cache.get(cache_key)
    if cached:
        return cached

    base_url = 'https://rest.sandbox.lalamove.com' if sandbox else 'https://rest.lalamove.com'

    payload = {
        'data': {
            'serviceType': 'MOTORCYCLE',
            'language': 'pt_BR',
            'stops': [
                {
                    'coordinates': {'lat': str(origin['lat']), 'lng': str(origin['lng'])},
                    'address': origin['address'],
                },
                {
                    'coordinates': {'lat': str(destination['lat']), 'lng': str(destination['lng'])},
                    'address': destination['address'],
                },
            ],
        }
    }

    ts = str(int(time.time() * 1000))
    body = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    message = f"{ts}\r\nPOST\r\n/v3/quotations\r\n\r\n{body}"
    signature = hmac_lib.new(
        api_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        'Authorization': f'hmac {api_key}:{ts}:{signature}',
        'Content-Type': 'application/json; charset=utf-8',
        'Market': 'BR',
    }

    resp = http_requests.post(
        f'{base_url}/v3/quotations',
        headers=headers,
        data=body.encode('utf-8'),
        timeout=10,
    )

    if resp.status_code >= 400:
        logger.error('[Lalamove] Erro na cotação: %s %s', resp.status_code, resp.text[:300])
        raise RuntimeError(f'Lalamove retornou erro {resp.status_code}.')

    data = resp.json()
    price_str = data['data']['priceBreakdown']['total']
    quotation_id = data['data']['quotationId']

    result = {
        'price': float(price_str),
        'eta': '30-45 min',
        'quotation_id': quotation_id,
    }
    cache.set(cache_key, result, 600)
    return result
```

- [ ] **Step 4: Executar os testes para confirmar que passam**

```bash
python manage.py test loja.tests.GetLalamoveQuotationTests
```

Esperado: `Ran 4 tests in 0.010s  OK`

- [ ] **Step 5: Executar toda a suite para garantir que nada quebrou**

```bash
python manage.py test loja
```

Esperado: todos os testes existentes continuam passando.

- [ ] **Step 6: Commit**

```bash
git add loja/integrations/lalamove.py loja/tests.py
git commit -m "feat: add get_lalamove_quotation with HMAC-SHA256 auth and caching"
```

---

### Task 5: Integração na view `calcular_frete_melhor_envio`

**Files:**
- Modify: `loja/views/shipping.py`
- Modify: `loja/tests.py`

> **Nota de ordem:** Os imports devem vir antes dos testes porque `@patch('loja.views.shipping.cep_to_coordinates')` exige que o atributo já exista no namespace do módulo; sem o import o decorator levanta `AttributeError` em vez do `AssertionError` esperado.

- [ ] **Step 1: Adicionar imports ao `loja/views/shipping.py`**

No topo de `loja/views/shipping.py`, após os imports existentes, adicione:

```python
from django.conf import settings
from ..integrations.lalamove import is_sao_paulo_cep, cep_to_coordinates, get_lalamove_quotation
```

- [ ] **Step 2: Escrever os testes de integração**

Adicione ao final de `loja/tests.py`:

```python
class LalamoveViewIntegrationTests(TestCase):
    @override_settings(
        LALAMOVE_API_KEY='key',
        LALAMOVE_API_SECRET='secret',
        LALAMOVE_SANDBOX=True,
        LALAMOVE_ORIGIN_LAT='-23.541',
        LALAMOVE_ORIGIN_LNG='-46.638',
        LALAMOVE_ORIGIN_ADDRESS='Rua Equestre 170, São Paulo',
        MELHOR_ENVIO_TOKEN='fake_token',
    )
    @patch('loja.views.shipping.get_lalamove_quotation')
    @patch('loja.views.shipping.cep_to_coordinates')
    @patch('loja.views.shipping.http_requests.post')
    def test_sp_cep_inclui_lalamove_como_primeira_opcao(
        self, mock_me_post, mock_coords, mock_quote
    ):
        mock_me_resp = Mock()
        mock_me_resp.status_code = 200
        mock_me_resp.json.return_value = [
            {'company': {'name': 'CORREIOS'}, 'name': 'PAC', 'price': '12.50', 'delivery_time': 7}
        ]
        mock_me_post.return_value = mock_me_resp

        mock_coords.return_value = {
            'lat': '-23.561', 'lng': '-46.656',
            'address': 'Avenida Paulista, São Paulo', 'cep': '01310100',
        }
        mock_quote.return_value = {
            'price': 19.90, 'eta': '30-45 min', 'quotation_id': 'QT-001',
        }

        resp = self.client.get('/frete/melhor-envio/?cep=01310100')
        data = resp.json()

        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(data['opcoes']), 1)
        primeira = data['opcoes'][0]
        self.assertEqual(primeira['empresa'], 'Lalamove')
        self.assertAlmostEqual(primeira['preco'], 19.90)
        self.assertEqual(primeira['prazo'], 0)
        self.assertEqual(primeira['eta'], '30-45 min')

    @override_settings(MELHOR_ENVIO_TOKEN='fake_token')
    @patch('loja.views.shipping.http_requests.post')
    def test_cep_fora_de_sp_nao_chama_lalamove(self, mock_me_post):
        mock_me_resp = Mock()
        mock_me_resp.status_code = 200
        mock_me_resp.json.return_value = [
            {'company': {'name': 'CORREIOS'}, 'name': 'PAC', 'price': '16.90', 'delivery_time': 10}
        ]
        mock_me_post.return_value = mock_me_resp

        with patch('loja.views.shipping.cep_to_coordinates') as mock_coords:
            resp = self.client.get('/frete/melhor-envio/?cep=20040020')
            mock_coords.assert_not_called()

        data = resp.json()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(any(op.get('empresa') == 'Lalamove' for op in data.get('opcoes', [])))

    @override_settings(
        LALAMOVE_ORIGIN_LAT='-23.541',
        LALAMOVE_ORIGIN_LNG='-46.638',
        LALAMOVE_ORIGIN_ADDRESS='Rua Equestre 170',
        MELHOR_ENVIO_TOKEN='fake_token',
    )
    @patch('loja.views.shipping.get_lalamove_quotation')
    @patch('loja.views.shipping.cep_to_coordinates')
    @patch('loja.views.shipping.http_requests.post')
    def test_falha_lalamove_nao_quebra_opcoes_me(self, mock_me_post, mock_coords, mock_quote):
        mock_me_resp = Mock()
        mock_me_resp.status_code = 200
        mock_me_resp.json.return_value = [
            {'company': {'name': 'CORREIOS'}, 'name': 'PAC', 'price': '12.50', 'delivery_time': 7}
        ]
        mock_me_post.return_value = mock_me_resp

        mock_coords.return_value = {
            'lat': '-23.561', 'lng': '-46.656',
            'address': 'Av Paulista, São Paulo', 'cep': '01310100',
        }
        mock_quote.side_effect = RuntimeError('Lalamove timeout')

        resp = self.client.get('/frete/melhor-envio/?cep=01310100')
        data = resp.json()

        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(data['opcoes']), 0)
        self.assertFalse(any(op.get('empresa') == 'Lalamove' for op in data['opcoes']))
```

- [ ] **Step 3: Executar os testes para confirmar que falham**

```bash
python manage.py test loja.tests.LalamoveViewIntegrationTests
```

Esperado: `AssertionError: 'CORREIOS' != 'Lalamove'` (bloco Lalamove ainda não existe na view)

- [ ] **Step 4: Adicionar o bloco Lalamove na view**

Dentro de `calcular_frete_melhor_envio`, localize a linha `opcoes.sort(key=lambda x: x['preco'])`. O bloco `return JsonResponse({'opcoes': opcoes})` que vem logo após deve ser substituído pelo seguinte (mantenha o `sort` intacto, substitua apenas o `return`):

```python
        opcoes.sort(key=lambda x: x['preco'])

        if is_sao_paulo_cep(cep_destino):
            try:
                dest = cep_to_coordinates(cep_destino)
                origin = {
                    'lat': settings.LALAMOVE_ORIGIN_LAT,
                    'lng': settings.LALAMOVE_ORIGIN_LNG,
                    'address': settings.LALAMOVE_ORIGIN_ADDRESS,
                }
                lala = get_lalamove_quotation(origin, dest)
                opcoes.insert(0, {
                    'id': 'lalamove-moto',
                    'nome': 'Motoboy · Entrega no mesmo dia',
                    'empresa': 'Lalamove',
                    'preco': lala['price'],
                    'prazo': 0,
                    'eta': lala['eta'],
                    'quotation_id': lala['quotation_id'],
                })
            except Exception:
                logger.warning('[Lalamove] Falha ao cotar CEP %s', cep_destino)

        return JsonResponse({'opcoes': opcoes})
```

- [ ] **Step 5: Executar os testes para confirmar que passam**

```bash
python manage.py test loja.tests.LalamoveViewIntegrationTests
```

Esperado: `Ran 3 tests in 0.040s  OK`

- [ ] **Step 6: Executar toda a suite**


```bash
python manage.py test loja
```

Esperado: todos os testes passam.

- [ ] **Step 7: Commit**

```bash
git add loja/views/shipping.py loja/tests.py
git commit -m "feat: integrate Lalamove motoboy option into shipping calculator for SP CEPs"
```

---

### Task 6: Fix de renderização de prazo em `detalhe.html`

**Files:**
- Modify: `loja/templates/detalhe.html` (linha 459)

- [ ] **Step 1: Localizar e substituir a linha**

Em `loja/templates/detalhe.html`, linha 459, substitua:

```javascript
prazo.textContent = `${op.empresa || ''} · até ${op.prazo} dias úteis`;
```

por:

```javascript
prazo.textContent = op.prazo === 0
  ? `${op.empresa || ''} · ${op.eta || 'Entrega hoje'}`
  : `${op.empresa || ''} · até ${op.prazo} dias úteis`;
```

- [ ] **Step 2: Verificar visualmente**

Suba o servidor (`python manage.py runserver`), abra a página de um produto, informe o CEP `01310-100` e clique em Calcular. Verifique que:
- A opção Lalamove aparece **primeiro** com o texto `Lalamove · 30-45 min`
- As opções PAC/SEDEX/Loggi continuam mostrando `Empresa · até X dias úteis`

- [ ] **Step 3: Commit**

```bash
git add loja/templates/detalhe.html
git commit -m "fix: display eta instead of '0 dias úteis' for Lalamove in product detail"
```

---

### Task 7: Fix de renderização de prazo em `carrinho.html`

**Files:**
- Modify: `loja/templates/carrinho.html` (linha 304)

- [ ] **Step 1: Localizar e substituir a linha**

Em `loja/templates/carrinho.html`, linha 304, substitua:

```javascript
<div class="opcao-prazo">${op.empresa} · ${op.prazo} dias úteis</div>
```

por:

```javascript
<div class="opcao-prazo">${op.prazo === 0 ? `${op.empresa} · ${op.eta || 'Entrega hoje'}` : `${op.empresa} · ${op.prazo} dias úteis`}</div>
```

- [ ] **Step 2: Verificar visualmente**

Adicione um produto ao carrinho, acesse `/carrinho/`, informe o CEP `01310-100` e calcule o frete. Verifique que:
- A opção Lalamove aparece **primeira**, selecionada por padrão, com `Lalamove · 30-45 min`
- As demais opções continuam exibindo dias úteis corretamente

- [ ] **Step 3: Executar a suite completa uma última vez**

```bash
python manage.py test loja
```

Esperado: todos os testes passam.

- [ ] **Step 4: Commit final**

```bash
git add loja/templates/carrinho.html
git commit -m "fix: display eta instead of '0 dias úteis' for Lalamove in cart"
```

---

## Notas de Implementação

**Resposta da API Lalamove v3:** O plano assume `data.priceBreakdown.total` como campo de preço e `data.quotationId` como ID. Se o sandbox retornar estrutura diferente, ajuste em `get_lalamove_quotation` na linha que lê `price_str` e `quotation_id`. Faça um `print(resp.json())` no primeiro teste com o sandbox real para confirmar a estrutura.

**Sandbox vs. Produção:** Com `LALAMOVE_SANDBOX=True` (padrão), a URL base é `https://rest.sandbox.lalamove.com`. Para ir a produção, configure `LALAMOVE_SANDBOX=False` no ambiente Railway.

**Rate limit Nominatim:** Nominatim exige máximo 1 req/s. O cache de 1 hora por CEP garante que a mesma requisição nunca seja feita com frequência. Não é necessário adicionar `time.sleep()`.
