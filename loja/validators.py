def cpf_valido(cpf):
    """Valida CPF com digitos verificadores, aceitando entrada com ou sem mascara."""
    numeros = ''.join(filter(str.isdigit, cpf or ''))
    if len(numeros) != 11 or numeros == numeros[0] * 11:
        return False

    for tamanho in (9, 10):
        soma = sum(int(numeros[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11
        if digito == 10:
            digito = 0
        if digito != int(numeros[tamanho]):
            return False
    return True
