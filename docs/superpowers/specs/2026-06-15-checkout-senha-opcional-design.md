# Design: Checkout sem senha obrigatória

**Data:** 2026-06-15  
**Status:** Aprovado

## Problema

O campo de senha obrigatório no checkout está causando abandono de carrinho. Clientes novos não querem criar uma conta — querem apenas comprar.

## Solução

Tornar o campo de senha opcional. Se o cliente não digitar, o backend gera uma senha aleatória, cria a conta e envia a senha por email imediatamente após o pedido.

---

## Mudanças por arquivo

### 1. `loja/templates/checkout.html`

- Remover `required` e `minlength="8"` do `<input type="password" name="senha">`
- Alterar placeholder para `"Deixe em branco para gerar automaticamente"`
- Alterar hint para `"Sua conta será criada automaticamente se você não digitar uma senha"`

### 2. `loja/views/cart.py`

**`_resolver_cliente(request, dados)`** — retorna tupla `(User | None, str | None)`:

| Cenário | Comportamento | Retorno |
|---|---|---|
| Usuário já logado | Sem mudança | `(user, None)` |
| Email existe + senha digitada | Autentica, loga sessão | `(user, None)` |
| Email existe + sem senha | Usa usuário existente, não loga | `(user, None)` |
| Email novo + senha digitada | Cria conta, loga sessão | `(user, None)` |
| Email novo + sem senha | Gera senha, cria conta, loga | `(user, senha_gerada)` |

Geração de senha: `secrets.token_urlsafe(9)` → 12 caracteres URL-safe.

**`checkout()`** — desempacota a tupla e dispara email se senha foi gerada:

```python
cliente, senha_gerada = _resolver_cliente(request, dados)
if cliente is None:
    return render_checkout()

pedido = _criar_pedido_com_itens(...)
if senha_gerada:
    enviar_email_conta_criada(pedido, senha_gerada)
_notificar_novo_pedido(pedido)
```

### 3. `loja/views/emails.py`

Nova função `enviar_email_conta_criada(pedido, senha)`:

- Disparada imediatamente após criação do pedido
- Usa os helpers existentes: `_email_wrapper`, `_paragrafo`, `_btn`, `_email_pedido_resumo`
- Mensagem central: "Sua conta foi criada automaticamente. Sua senha é: XXXXX — você pode alterá-la depois em Minha Conta."
- Inclui resumo do pedido e botão para finalizar pagamento
- Usa `enfileirar_email_pendente` como fallback em caso de falha no envio

---

## Fora do escopo

- Sem migração de banco
- Sem mudança no fluxo de usuários logados
- Sem mudança em cupons, frete ou pagamento
- Sem mudança no fluxo de email dos usuários que digitam a senha
