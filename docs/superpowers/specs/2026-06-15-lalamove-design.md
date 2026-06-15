# Integração Lalamove — Design Spec

**Data:** 2026-06-15  
**Status:** Aprovado  
**Escopo:** Adicionar cotação de frete motoboy (Lalamove v3) para CEPs de São Paulo no calculador de frete existente.

---

## Contexto

O projeto já possui um calculador de frete via Melhor Envio (`/frete/melhor-envio/`) que retorna um array `opcoes`. A UI em `detalhe.html` e `carrinho.html` renderiza cada item do array sem distinção de fornecedor. A integração Lalamove aproveita essa estrutura sem alterar nenhum arquivo de template ou JavaScript.

---

## Arquitetura

### Abordagem: Backend Aggregation no endpoint existente

Quando o CEP de destino é de São Paulo, o endpoint `/frete/melhor-envio/` chama a Lalamove após obter as opções do Melhor Envio e insere o resultado no topo da lista antes de retornar. Falhas do Lalamove são silenciosas — as opções do Melhor Envio continuam aparecendo normalmente.

### Arquivos alterados/criados

```
loja/
├── integrations/
│   └── lalamove.py           ← NOVO
├── views/
│   └── shipping.py           ← MODIFICADO (bloco Lalamove no fim de calcular_frete_melhor_envio)
barrs_store/
└── settings.py               ← MODIFICADO (6 novas variáveis)
.env.example                  ← MODIFICADO (6 novas entradas)
```

**Não mudam:** `urls.py`, `detalhe.html`, `carrinho.html`, CSS, JS.

---

## `loja/integrations/lalamove.py`

### `is_sao_paulo_cep(cep: str) -> bool`

- Limpa o CEP (remove hífen e espaços), valida 8 dígitos
- Retorna `True` se estiver nos ranges de SP:
  - 01000000–05999999
  - 08000000–08499999

### `cep_to_coordinates(cep: str) -> dict`

Pipeline:
1. Chama ViaCEP (`viacep.com.br/ws/{cep}/json/`) para obter logradouro, bairro, localidade, UF
2. Monta string de endereço e chama Nominatim (`nominatim.openstreetmap.org/search?q=...&format=json&limit=1&countrycodes=br`)
3. Retorna `{"lat": str, "lng": str, "address": str}`

Cache: chave `lalamove:coords:{cep}`, TTL 1 hora (endereço não muda).

### `get_lalamove_quotation(origin: dict, destination: dict) -> dict`

Parâmetros: `origin` e `destination` com chaves `lat`, `lng`, `address`.

**Assinatura HMAC-SHA256:**
```python
ts = str(int(time.time() * 1000))
body = json.dumps(payload)
message = f"{ts}\r\nPOST\r\n/v3/quotations\r\n\r\n{body}"
signature = hmac.new(secret.encode(), message.encode(), sha256).hexdigest()
# Header: Authorization: hmac {key}:{ts}:{signature}
```

**Payload:**
```json
{
  "data": {
    "serviceType": "MOTORCYCLE",
    "stops": [
      {"coordinates": {"lat": "...", "lng": "..."}, "address": "..."},
      {"coordinates": {"lat": "...", "lng": "..."}, "address": "..."}
    ]
  }
}
```

**URL base:**
- Sandbox: `https://rest.sandbox.lalamove.com`
- Produção: `https://rest.lalamove.com`

Controlado por `settings.LALAMOVE_SANDBOX`.

**Retorno:** `{"price": float, "eta": "30-45 min", "quotation_id": str}`

Cache: chave `lalamove:quote:{cep_destino}`, TTL 10 minutos.

Levanta `RuntimeError` com mensagem amigável em caso de erro de API.

---

## `loja/views/shipping.py` — Modificação

No final de `calcular_frete_melhor_envio`, após montar `opcoes` e antes do `return JsonResponse`:

```python
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
```

A opção Lalamove aparece **primeiro** na lista (entrega mais rápida no topo).

---

## Configurações

### `settings.py`

```python
LALAMOVE_API_KEY        = os.environ.get('LALAMOVE_API_KEY', '')
LALAMOVE_API_SECRET     = os.environ.get('LALAMOVE_API_SECRET', '')
LALAMOVE_SANDBOX        = os.environ.get('LALAMOVE_SANDBOX', 'True') == 'True'
LALAMOVE_ORIGIN_LAT     = os.environ.get('LALAMOVE_ORIGIN_LAT', '')
LALAMOVE_ORIGIN_LNG     = os.environ.get('LALAMOVE_ORIGIN_LNG', '')
LALAMOVE_ORIGIN_ADDRESS = os.environ.get('LALAMOVE_ORIGIN_ADDRESS', '')
```

Quando `LALAMOVE_API_KEY` está vazio, a chamada falha imediatamente com exceção capturada silenciosamente — sem efeito colateral.

### `.env.example`

```
LALAMOVE_API_KEY=
LALAMOVE_API_SECRET=
LALAMOVE_SANDBOX=True
LALAMOVE_ORIGIN_LAT=
LALAMOVE_ORIGIN_LNG=
LALAMOVE_ORIGIN_ADDRESS=
```

---

## Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| Ponto de integração | Backend aggregation no endpoint existente | Zero mudanças em frontend/templates |
| Geocoding | Nominatim (OpenStreetMap) | Gratuito, sem chave API, suficiente com cache |
| Falha Lalamove | Silenciosa com `logger.warning` | Não degrada as opções do Melhor Envio |
| Cache coordenadas | 1 hora | Endereço de um CEP não muda |
| Cache cotação | 10 minutos | Preço pode variar; evita excesso de chamadas |
| Posição na lista | Primeiro (`insert(0, ...)`) | Entrega mais rápida deve aparecer no topo |
| Ranges SP | 01000000–05999999 e 08000000–08499999 | Ranges oficiais dos Correios para SP capital |
