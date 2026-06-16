# Sugestão Técnica: Entrega Agrupada via Admin (Lalamove)

**Status:** Não implementado — sugestão futura  
**Data:** 2026-06-16

## Objetivo

Permitir que o admin selecione múltiplos pedidos pagos de São Paulo e envie todos
num único motoboy com rota otimizada — mais barato que N entregas individuais.

## Como funcionaria

### 1. Seleção no Admin

Adicionar uma **action** na listagem de pedidos (`PedidoAdmin.actions`):

```python
@admin.action(description='Agrupar entrega Lalamove (rota única)')
def agrupar_entrega_lalamove(modeladmin, request, queryset):
    ...
```

Filtros automáticos: apenas pedidos com `status='confirmado'`,
`frete_transportadora='lalamove'` e `lalamove_order_id` vazio.

### 2. Cotação com múltiplos stops

A API Lalamove v3 aceita até N stops numa única cotação.
O payload seria:

```json
{
  "data": {
    "serviceType": "LALAGO",
    "isRouteOptimized": true,
    "stops": [
      { "coordinates": {...}, "address": "Barrs Store (origem)" },
      { "coordinates": {...}, "address": "Endereço cliente 1" },
      { "coordinates": {...}, "address": "Endereço cliente 2" },
      { "coordinates": {...}, "address": "Endereço cliente 3" }
    ]
  }
}
```

`isRouteOptimized: true` deixa a Lalamove reordenar as paradas para
minimizar distância — reduz custo e tempo.

### 3. Tela de confirmação

Antes de criar o pedido na Lalamove, exibir uma página intermediária com:
- Lista de pedidos selecionados
- Endereços de entrega
- Valor total da rota cotada
- Botão **"Confirmar e solicitar motoboy"**

### 4. Criação do pedido agrupado

Após confirmação, criar um único `order` na Lalamove com todos os `stopIds`
retornados pela cotação. Cada pedido recebe o mesmo `lalamove_order_id`.

### 5. Impacto esperado

- Custo por entrega reduzido (uma corrida vs N corridas)
- Mesmo motoboy entrega todos os pedidos do lote
- Admin mantém controle total (aprovação manual obrigatória)

## Pré-requisitos antes de implementar

- Validar limite máximo de stops por cotação na API (verificar docs Lalamove)
- Confirmar comportamento do `shareLink` para múltiplos destinatários
- Definir o que fazer se um pedido do lote falhar na criação
