import hashlib
import json
import logging
import os

import requests as http_requests

from django.urls import reverse

from ..models import EmailPendente
from .utils import (
    site_url,
    dominio_email_para_log,
    resposta_externa_segura_para_log,
)

logger = logging.getLogger(__name__)

EMAIL_LOGO_URL = 'https://res.cloudinary.com/dsw5fkmwp/image/upload/q_auto/f_auto/v1777401449/ChatGPT_Image_28_de_abr._de_2026_15_37_19_ovzkth.png'
EMAIL_BRAND_NAME = 'Barrs Store'


def enfileirar_email_pendente(payload, motivo='', pedido_id=None, tipo=''):
    destinatarios = payload.get('to') or [{}]
    destinatario = destinatarios[0] if destinatarios else {}
    if pedido_id and tipo:
        # Chave estavel: garante dedupe em retentativas do webhook MP, mesmo que o payload varie.
        dedupe_raw = f'pedido:{pedido_id}:tipo:{tipo}'
    else:
        dedupe_raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    dedupe_key = hashlib.sha256(dedupe_raw.encode('utf-8')).hexdigest()
    email_pendente, criado = EmailPendente.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            'destinatario_email': destinatario.get('email', ''),
            'destinatario_nome': destinatario.get('name', ''),
            'assunto': payload.get('subject', '')[:200],
            'payload': payload,
            'ultimo_erro': motivo[:1000],
        },
    )
    if not criado and email_pendente.status == 'enviado':
        return email_pendente
    if not criado and motivo:
        email_pendente.ultimo_erro = motivo[:1000]
        email_pendente.save(update_fields=['ultimo_erro', 'atualizado_em'])
    return email_pendente


def enviar_brevo_payload(payload, timeout=10):
    brevo_api_key = os.environ.get('BREVO_API_KEY', '').strip()
    if not brevo_api_key:
        return False, 'BREVO_API_KEY nao configurada.', None
    try:
        resposta = http_requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'accept': 'application/json', 'api-key': brevo_api_key, 'Content-Type': 'application/json'},
            json=payload,
            timeout=timeout,
        )
        if resposta.status_code >= 400:
            return False, f'Brevo status {resposta.status_code}', resposta
        return True, '', resposta
    except Exception as exc:
        return False, str(exc), None


# ── HELPERS DE EMAIL ──────────────────────────────────────────────
def _brevo_sender():
    return {
        'name': os.environ.get('BREVO_FROM_NAME', 'Barrs Store | Atendimento').strip(),
        'email': os.environ.get('BREVO_FROM_EMAIL', 'contato.barrsstore@gmail.com').strip(),
    }


def _brevo_send(assunto, html, destinatario_email, destinatario_nome):
    payload = _brevo_payload(destinatario_email, destinatario_nome, assunto, html)
    ok, erro, resposta = enviar_brevo_payload(payload)
    if ok:
        return True
    enfileirar_email_pendente(payload, erro)
    if resposta is not None:
        logger.warning('[BREVO] E-mail "%s" enfileirado: %s', assunto, resposta_externa_segura_para_log(resposta))
    else:
        logger.warning('[BREVO] E-mail "%s" enfileirado. email_domain=%s erro=%s', assunto, dominio_email_para_log(destinatario_email), erro)
    return False


def _paragrafo(texto):
    return f'<p style="font-size:14px;color:#6B5E53;line-height:1.7;margin:0 0 16px">{texto}</p>'


def _email_icon(nome='gem', size=22, color='#738269'):
    icons = {
        'gem': '<path d="M6 3h12l4 6-10 12L2 9l4-6Z"/><path d="M2 9h20"/><path d="m6 3 6 18 6-18"/><path d="M6 3 2 9"/><path d="m18 3 4 6"/>',
        'heart': '<path d="M19.5 12.6 12 20l-7.5-7.4a5 5 0 0 1 7.1-7.1l.4.4.4-.4a5 5 0 0 1 7.1 7.1Z"/>',
        'truck': '<path d="M3 7h11v10H3z"/><path d="M14 10h4l3 3v4h-7z"/><circle cx="7" cy="19" r="2"/><circle cx="18" cy="19" r="2"/>',
        'message': '<path d="M21 12a8 8 0 0 1-8 8H7l-4 3 1.4-5.2A8 8 0 1 1 21 12Z"/>',
        'bag': '<path d="M6 8h12l-1 13H7L6 8Z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
        'check': '<path d="M20 6 9 17l-5-5"/>',
        'leaf': '<path d="M5 19c9 0 14-6 14-14-8 0-14 5-14 14Z"/><path d="M5 19 19 5"/>',
    }
    paths = icons.get(nome, icons['gem'])
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="display:inline-block;vertical-align:middle">{paths}</svg>'


def _email_wrapper(titulo, corpo_html, preheader=''):
    preheader_html = preheader or titulo
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    @media only screen and (max-width: 620px) {{
      .email-outer {{ padding: 0 !important; }}
      .email-shell {{ width: 100% !important; border-radius: 0 !important; }}
      .email-pad {{ padding-left: 22px !important; padding-right: 22px !important; }}
      .email-title {{ font-size: 28px !important; }}
      .email-btn a {{ display: block !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#F5F2EC;font-family:Montserrat,Arial,sans-serif;color:#6B5E53">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{preheader_html}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#F5F2EC">
    <tr>
      <td class="email-outer" align="center" style="padding:28px 12px">
        <table role="presentation" class="email-shell" width="600" cellspacing="0" cellpadding="0" border="0" style="width:600px;max-width:600px;background:#FFFFFF;border-radius:26px;overflow:hidden;border:1px solid #E8E3D8;box-shadow:0 20px 58px rgba(61,45,32,0.12)">
          <tr>
            <td class="email-pad" bgcolor="#6F7E66" style="padding:34px 38px;background:#6F7E66;background:linear-gradient(135deg,#56634F 0%,#7A866F 58%,#A99668 100%);text-align:center">
              <img src="{EMAIL_LOGO_URL}" width="70" height="70" alt="{EMAIL_BRAND_NAME}" style="display:block;margin:0 auto 14px;border-radius:50%;border:1px solid rgba(255,255,255,0.55);box-shadow:0 10px 28px rgba(38,31,22,0.22)">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:0 auto">
                <tr>
                  <td bgcolor="#FFFFFF" style="background:#FFFFFF;border-radius:999px;padding:9px 22px;border:1px solid #E8D6A3;box-shadow:0 8px 22px rgba(38,31,22,0.12)">
                    <span style="display:block;color:#3D2D20;font-family:Georgia,'Times New Roman',serif;font-size:26px;line-height:1;font-weight:700;letter-spacing:-0.02em">{EMAIL_BRAND_NAME}</span>
                  </td>
                </tr>
              </table>
              <p style="margin:10px auto 16px;width:72px;height:1px;background:#E8D6A3;line-height:1px;font-size:1px">&nbsp;</p>
              <h1 class="email-title" style="margin:0;color:#FFFFFF;font-family:Georgia,'Times New Roman',serif;font-size:32px;line-height:1.05;font-weight:700;letter-spacing:-0.03em">{titulo}</h1>
            </td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:34px 38px 30px">{corpo_html}</td>
          </tr>
          <tr>
            <td class="email-pad" style="padding:22px 38px;background:#FBFAF7;border-top:1px solid #E8E3D8;text-align:center">
              <p style="margin:0 0 8px;color:#9E9488;font-size:12px;line-height:1.6">Duvidas sobre seu pedido? Fale com a gente pelo WhatsApp.</p>
              <p style="margin:0;color:#9E9488;font-size:11px;line-height:1.6">© 2026 Barrs Store · <a href="https://www.barrsstore.com.br" style="color:#738269;text-decoration:none">barrsstore.com.br</a></p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _btn(texto, url, cor='#738269'):
    return f'<span class="email-btn"><a href="{url}" style="display:inline-block;padding:14px 28px;background:{cor};color:#fff;border-radius:999px;text-decoration:none;font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;box-shadow:0 10px 22px rgba(83,98,76,0.18)">{texto}</a></span>'


def _email_pedido_resumo(pedido):
    itens_html = ''.join([
        f"""
        <tr>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#3D342C;font-size:14px;line-height:1.35">
            <strong style="font-family:Georgia,'Times New Roman',serif;font-size:15px">{item.nome_produto}</strong>
          </td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#6B5E53;font-size:13px;text-align:center">{item.quantidade}</td>
          <td style="padding:13px 0;border-bottom:1px solid #E8E3D8;color:#738269;font-size:14px;font-weight:700;text-align:right">R$ {item.preco_unitario}</td>
        </tr>
        """
        for item in pedido.itens.select_related('produto').all()
    ])
    frete_texto = f"R$ {pedido.frete}" if pedido.frete > 0 else "Gratis"
    desconto_html = ''
    if pedido.desconto > 0:
        desconto_html = f"""
        <tr>
          <td colspan="2" style="padding-top:10px;color:#9E9488;font-size:13px">Desconto {pedido.cupom_codigo}</td>
          <td style="padding-top:10px;color:#738269;font-size:13px;font-weight:700;text-align:right">- R$ {pedido.desconto}</td>
        </tr>
        """
    return f"""
      <div style="background:#FBFAF7;border:1px solid #E8E3D8;border-radius:18px;padding:20px;margin:24px 0">
        <p style="margin:0 0 14px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Resumo do pedido #{pedido.id}</p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="border-collapse:collapse">
          <tr>
            <th align="left" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Produto</th>
            <th align="center" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Qtd</th>
            <th align="right" style="padding-bottom:8px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.10em;text-transform:uppercase">Valor</th>
          </tr>
          {itens_html}
          <tr>
            <td colspan="2" style="padding-top:14px;color:#9E9488;font-size:13px">Subtotal</td>
            <td style="padding-top:14px;color:#6B5E53;font-size:13px;text-align:right">R$ {pedido.subtotal}</td>
          </tr>
          <tr>
            <td colspan="2" style="padding-top:8px;color:#9E9488;font-size:13px">Frete</td>
            <td style="padding-top:8px;color:#6B5E53;font-size:13px;text-align:right">{frete_texto}</td>
          </tr>
          {desconto_html}
          <tr>
            <td colspan="2" style="padding-top:12px;color:#3D2D20;font-size:16px;font-weight:700">Total</td>
            <td style="padding-top:12px;color:#738269;font-size:17px;font-weight:800;text-align:right">R$ {pedido.total}</td>
          </tr>
        </table>
      </div>
    """


def _email_entrega(pedido):
    return f"""
      <div style="background:#F5F2EC;border-radius:16px;padding:18px;margin:20px 0">
        <p style="margin:0 0 10px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Entrega</p>
        <p style="margin:0;color:#6B5E53;font-size:14px;line-height:1.7">
          {pedido.rua}, {pedido.numero}{f" - {pedido.complemento}" if pedido.complemento else ""}<br>
          {pedido.bairro} - {pedido.cidade}/{pedido.estado}<br>
          CEP {pedido.cep}
        </p>
      </div>
    """


def _brevo_payload(destinatario_email, destinatario_nome, assunto, html):
    return {
        'sender': _brevo_sender(),
        'to': [{'email': destinatario_email, 'name': destinatario_nome}],
        'subject': assunto,
        'htmlContent': html,
    }


def enviar_email_confirmacao(pedido):
    """Envia e-mail premium de confirmacao para o cliente via Brevo."""
    try:
        link_acompanhar = site_url(reverse('rastrear_pedido'))
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pagamento foi aprovado e seu pedido ja entrou em preparo com todo o cuidado da Barrs Store.')
            + _email_pedido_resumo(pedido)
            + _email_entrega(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar pedido", link_acompanhar)}</div>'
            + _paragrafo('<span style="color:#9E9488;font-size:13px">Assim que o envio for atualizado, voce recebera o codigo de rastreio automaticamente por e-mail.</span>')
        )
        html = _email_wrapper('Pedido confirmado', corpo, f'Pedido #{pedido.id} confirmado. Total: R$ {pedido.total}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Pedido #{pedido.id} confirmado - Barrs Store', html)
        brevo_admin_email = os.environ.get('BREVO_ADMIN_EMAIL', payload['sender']['email']).strip()
        if brevo_admin_email and brevo_admin_email.lower() != pedido.email.lower():
            payload['bcc'] = [{'email': brevo_admin_email, 'name': EMAIL_BRAND_NAME}]

        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Confirmacao pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='confirmacao')
            logger.warning('E-mail do pedido %s enfileirado para reenvio. erro=%s', pedido.id, erro)
            return False
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail Brevo do pedido %s: %s', pedido.id, exc)
        return False


def enviar_email_pagamento_pendente(pedido):
    """Envia um lembrete premium com link para finalizar o pagamento."""
    if pedido.email_pagamento_pendente_enviado:
        return True
    try:
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pedido foi reservado e esta aguardando a finalizacao do pagamento.')
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Finalizar pagamento", link_pagamento)}</div>'
            + _paragrafo('<span style="color:#9E9488;font-size:13px">Se voce ja pagou, pode ignorar este e-mail. A confirmacao acontece automaticamente assim que o pagamento for aprovado.</span>')
        )
        html = _email_wrapper('Seu pedido foi reservado', corpo, f'Finalize o pagamento do pedido #{pedido.id}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Finalize o pagamento do pedido #{pedido.id} - Barrs Store', html)
        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Pagamento pendente pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if ok:
            pedido.email_pagamento_pendente_enviado = True
            pedido.save(update_fields=['email_pagamento_pendente_enviado'])
            return True
        enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='pagamento_pendente')
        logger.warning('E-mail de pagamento pendente do pedido %s enfileirado. erro=%s', pedido.id, erro)
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de pagamento pendente do pedido %s: %s', pedido.id, exc)
    return False


def enviar_email_rastreio(pedido):
    """Envia o codigo de rastreio ao cliente quando o pedido for enviado."""
    if not pedido.codigo_rastreio:
        return False
    try:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        corpo = (
            _paragrafo(f'Ola, <strong style="color:#3D2D20">{pedido.nome}</strong>. Seu pedido #{pedido.id} ja foi enviado.')
            + f"""
              <div style="background:#FBFAF7;border:1px solid #E8E3D8;border-radius:18px;padding:20px;margin:24px 0">
                <p style="margin:0 0 10px;color:#9E9488;font-size:11px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Rastreio</p>
                <p style="margin:0 0 8px;color:#3D2D20;font-size:16px;font-weight:700">{pedido.codigo_rastreio}</p>
                <p style="margin:0;color:#6B5E53;font-size:14px;line-height:1.6">Transportadora: {transportadora}</p>
              </div>
            """
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar entrega", rastreio_url)}</div>'
            + _paragrafo(f'<span style="color:#9E9488;font-size:13px">Caso o botao nao abra, acesse este link: <a href="{rastreio_url}" style="color:#738269;text-decoration:none">{rastreio_url}</a></span>')
        )
        html = _email_wrapper('Seu pedido foi enviado', corpo, f'Codigo de rastreio do pedido #{pedido.id}: {pedido.codigo_rastreio}.')
        payload = _brevo_payload(pedido.email, pedido.nome, f'Seu pedido #{pedido.id} foi enviado - Barrs Store', html)
        ok, erro, resposta = enviar_brevo_payload(payload)
        logger.info('[BREVO] Rastreio pedido %s: %s', pedido.id, resposta_externa_segura_para_log(resposta) if resposta else erro)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='rastreio')
            logger.warning('E-mail de rastreio do pedido %s enfileirado. erro=%s', pedido.id, erro)
            return False
        pedido.email_rastreio_enviado = True
        pedido.save(update_fields=['email_rastreio_enviado'])
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar e-mail de rastreio do pedido %s: %s', pedido.id, exc)
        return False


# ── SEQUÊNCIA PÓS-COMPRA PREMIUM ──────────────────────────────────

def _enviar_poscompra(pedido, etapa, assunto, html):
    ok = _brevo_send(assunto, html, pedido.email, pedido.nome)
    if ok:
        flag = f'email_poscompra_{etapa}_enviado'
        setattr(pedido, flag, True)
        pedido.save(update_fields=[flag])
    return ok


def enviar_email_poscompra_1(pedido):
    """E-mail 1 (≈1h após confirmação): pedido em preparo."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    corpo = (
        f'<div style="text-align:center;margin:0 0 18px">{_email_icon("gem", 30)}</div>'
        + _paragrafo(f'Oi, <strong>{pedido.nome.split()[0]}</strong>! Que alegria receber seu pedido.')
        + _paragrafo('Já estamos separando cada peça com muito cuidado para garantir que chegue até você perfeita. A Barrs Store cuida de cada detalhe — da embalagem à entrega.')
        + _paragrafo(f'<strong>Pedido #{pedido.id}</strong> · Total: <strong style="color:#8A947C">R$ {pedido.total}</strong>')
        + f'<div style="text-align:center;margin:28px 0">{_btn("Acompanhar meu pedido", link_rastrear)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Em breve você receberá o código de rastreio. Se tiver qualquer dúvida, estamos no WhatsApp.</span>')
    )
    return _enviar_poscompra(pedido, 1, f'Seu pedido #{pedido.id} está sendo preparado — Barrs Store', _email_wrapper('Seu pedido está em boas mãos', corpo))


def enviar_email_poscompra_2(pedido):
    """E-mail 2 (≈24h após confirmação): bastidores da marca."""
    link_loja = site_url('/')
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, enquanto preparamos seu pedido com todo o carinho, queríamos te contar um pouquinho sobre como trabalhamos por aqui.')
        + _paragrafo('Cada peça da Barrs Store passa por uma curadoria criteriosa. Acreditamos que um acessório bem escolhido não é apenas um adorno — é uma extensão da sua personalidade.')
        + '<div style="background:#F5F2EC;border-radius:10px;padding:20px;margin:20px 0">'
        + '<p style="font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#9E9488;margin:0 0 12px">DICA DE CUIDADO</p>'
        + _paragrafo('Guarde suas peças em local seco, longe de perfumes e produtos químicos. Para anéis e pulseiras, evite contato com água. Assim, elas duram muito mais.')
        + '</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Ver novidades na loja", link_loja)}</div>'
    )
    return _enviar_poscompra(pedido, 2, f'Um cuidado especial sobre seu pedido #{pedido.id} — Barrs Store', _email_wrapper('O cuidado que vai junto com cada peça', corpo))


def enviar_email_poscompra_3(pedido):
    """E-mail 3 (≈3 dias): atualização de envio / rastreio."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    if pedido.codigo_rastreio:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        trecho_rastreio = (
            '<div style="background:#E8EDE3;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center">'
            + f'<p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#8A947C;margin:0 0 6px">CÓDIGO DE RASTREIO</p>'
            + f'<p style="font-size:18px;font-weight:700;color:#3d2d20;margin:0;letter-spacing:1px">{pedido.codigo_rastreio}</p>'
            + f'<p style="font-size:12px;color:#9E9488;margin:6px 0 0">{transportadora}</p>'
            + '</div>'
            + f'<div style="text-align:center;margin:20px 0">{_btn("Rastrear minha encomenda", rastreio_url)}</div>'
        )
        subtitulo = 'Seu pedido saiu para entrega'
        intro = _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, uma ótima notícia! Seu pedido #{pedido.id} foi enviado e já está a caminho.')
    else:
        trecho_rastreio = (
            _paragrafo('Estamos finalizando o preparo do seu pedido e em breve ele sairá para entrega. Você receberá o código de rastreio assim que for despachado.')
            + f'<div style="text-align:center;margin:24px 0">{_btn("Rastrear pedido", link_rastrear)}</div>'
        )
        subtitulo = 'Seu pedido está quase pronto'
        intro = _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, o pedido #{pedido.id} está nos últimos detalhes de preparo!')

    corpo = intro + trecho_rastreio + _paragrafo('<span style="color:#9E9488;font-size:13px">Qualquer dúvida, estamos no WhatsApp. Mal podemos esperar para você receber suas peças.</span>')
    return _enviar_poscompra(pedido, 3, f'Atualização do seu pedido #{pedido.id} — Barrs Store', _email_wrapper(subtitulo, corpo))


def enviar_email_poscompra_4(pedido):
    """E-mail 4 (≈7 dias): pós-entrega estimada, verificação."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    link_wa = 'https://wa.me/5511913225256'
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, já faz alguns dias desde que enviamos seu pedido. Chegou tudo certinho?')
        + _paragrafo('Adoraríamos saber como está sendo a experiência com suas novas peças. Se tiver qualquer dúvida sobre a entrega, estamos aqui para resolver com agilidade.')
        + '<div style="display:flex;gap:12px;margin:24px 0;justify-content:center;flex-wrap:wrap">'
        + f'<a href="{link_wa}" style="display:inline-block;padding:12px 24px;background:#25d366;color:#fff;border-radius:999px;text-decoration:none;font-size:13px;font-weight:700">{_email_icon("message", 16, "#ffffff")} <span style="vertical-align:middle">Falar no WhatsApp</span></a>'
        + f'<a href="{link_rastrear}" style="display:inline-block;padding:12px 24px;background:#F5F2EC;color:#6B5E53;border:1px solid #D9D3C7;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">Rastrear pedido</a>'
        + '</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Sua satisfação é o que nos move a continuar criando peças exclusivas com tanto cuidado.</span>')
    )
    return _enviar_poscompra(pedido, 4, f'Tudo certo com seu pedido #{pedido.id}, {pedido.nome.split()[0]}? — Barrs Store', _email_wrapper('Chegou tudo bem?', corpo))


def enviar_email_poscompra_5(pedido):
    """E-mail 5 (≈15 dias): fidelização e retorno à loja."""
    link_loja = site_url('/')
    link_wa = 'https://wa.me/5511913225256'
    corpo = (
        _paragrafo(f'<strong>{pedido.nome.split()[0]}</strong>, obrigada de verdade por escolher a Barrs Store.')
        + _paragrafo('Clientes como você são a razão de cada detalhe que dedicamos às nossas peças — da curadoria à embalagem. Você é especial para a gente.')
        + '<div style="background:#F5F2EC;border-radius:10px;padding:20px;margin:20px 0;text-align:center">'
        + f'<div style="margin:0 0 10px">{_email_icon("leaf", 22)}</div>'
        + '<p style="font-size:13px;font-weight:600;color:#3d2d20;margin:0 0 8px">Novidades chegando todo mês</p>'
        + _paragrafo('<span style="font-size:13px;color:#9E9488">Acompanhe nossas novidades no Instagram e seja a primeira a saber dos lançamentos exclusivos.</span>')
        + f'<a href="https://www.instagram.com/barrsstore" style="display:inline-block;margin-top:8px;padding:10px 22px;background:#8A947C;color:#fff;border-radius:8px;text-decoration:none;font-size:13px;font-weight:600">@barrsstore no Instagram</a>'
        + '</div>'
        + f'<div style="text-align:center;margin:20px 0">{_btn("Ver novas peças na loja", link_loja)}</div>'
        + _paragrafo(f'<span style="color:#9E9488;font-size:13px">Tem alguma peça dos sonhos? Me conta pelo <a href="{link_wa}" style="color:#8A947C">WhatsApp</a> — amo ajudar.</span>')
    )
    return _enviar_poscompra(pedido, 5, f'Obrigada, {pedido.nome.split()[0]} — Barrs Store', _email_wrapper('Uma mensagem especial para você', corpo))


# ── SEQUÊNCIA ABANDONO DE CARRINHO PREMIUM ─────────────────────────

def enviar_email_abandono_1(carrinho):
    """E-mail 1 (≈1h): primeiro contato suave."""
    if not carrinho.email_cliente:
        return False
    link_checkout = carrinho.link_checkout()
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False

    itens_html = ''.join([
        f'<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid #E8EDE3">'
        + (f'<img src="{item.produto.imagem.url}" alt="{item.produto.nome}" style="width:52px;height:52px;border-radius:8px;object-fit:cover;background:#E8EDE3;flex-shrink:0">'
           if item.produto.imagem else
           f'<div style="width:52px;height:52px;border-radius:8px;background:#E8EDE3;display:flex;align-items:center;justify-content:center;flex-shrink:0">{_email_icon("gem", 22)}</div>')
        + f'<div style="flex:1"><p style="font-size:13px;font-weight:600;color:#3d2d20;margin:0">{item.produto.nome}</p>'
        + (f'<p style="font-size:11px;color:#8A947C;margin:2px 0 0">Tamanho: {item.tamanho}</p>' if item.tamanho else '')
        + f'</div><p style="font-size:14px;font-weight:600;color:#8A947C;flex-shrink:0">R$ {item.subtotal()}</p></div>'
        for item in itens
    ])

    corpo = (
        _paragrafo('Você deixou algumas peças especiais no carrinho.')
        + _paragrafo('Não queremos que essas peças fiquem esperando sem você. Seu carrinho ainda está salvo, exatamente como você deixou.')
        + f'<div style="background:#F5F2EC;border-radius:10px;padding:16px 20px;margin:20px 0">{itens_html}</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Finalizar minha compra", link_checkout)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:13px">Com dúvida sobre tamanho ou entrega? Estamos no WhatsApp, é só chamar.</span>')
    )
    html = _email_wrapper('Você esqueceu algo especial', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Seu carrinho ainda está aqui — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_1_enviado = True
        carrinho.save(update_fields=['email_abandono_1_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_2(carrinho):
    """E-mail 2 (≈24h): destaca benefícios e produtos."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()
    total = carrinho.total()

    corpo = (
        _paragrafo('Suas peças ainda estão esperando por você.')
        + _paragrafo('Percebemos que algumas peças ficaram no seu carrinho. Elas combinam muito com você.')
        + '<div style="background:#E8EDE3;border-radius:10px;padding:16px 20px;margin:20px 0">'
        + '<p style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#8A947C;margin:0 0 10px">POR QUE COMPRAR NA BARRS STORE</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 8px;line-height:1.6">{_email_icon("truck", 15)} &nbsp;Entrega para todo o Brasil</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 8px;line-height:1.6">{_email_icon("gem", 15)} &nbsp;Semijoias com acabamento premium</p>'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0;line-height:1.6">{_email_icon("message", 15)} &nbsp;Atendimento humanizado via WhatsApp</p>'
        + '</div>'
        + f'<p style="font-size:15px;font-weight:600;color:#3d2d20;margin:16px 0">Total do carrinho: <span style="color:#8A947C">R$ {total}</span></p>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Garantir meu pedido agora", link_checkout)}</div>'
    )
    html = _email_wrapper('Suas peças estão esperando por você', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Ainda dá tempo — seu carrinho está salvo — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_2_enviado = True
        carrinho.save(update_fields=['email_abandono_2_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_3(carrinho):
    """E-mail 3 (≈48h): urgência suave, última mensagem."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()

    corpo = (
        _paragrafo('Esta é nossa última mensagem sobre seu carrinho — prometemos.')
        + _paragrafo('Só queríamos lembrar que os estoques da Barrs Store são limitados. Não queremos que você perca as peças que escolheu com tanto cuidado.')
        + '<div style="background:#F5F2EC;border:1px solid #D9D3C7;border-radius:10px;padding:16px 20px;margin:20px 0;text-align:center">'
        + f'<p style="font-size:13px;color:#6B5E53;margin:0 0 4px">Você tem <strong>{sum(i.quantidade for i in itens)} peça(s)</strong> reservada(s)</p>'
        + f'<p style="font-size:18px;font-weight:700;color:#8A947C;margin:0">R$ {carrinho.total()}</p>'
        + '</div>'
        + f'<div style="text-align:center;margin:24px 0">{_btn("Finalizar antes que esgote", link_checkout)}</div>'
        + _paragrafo('<span style="color:#9E9488;font-size:12px">Se mudou de ideia, sem problema — não vamos te incomodar mais. Mas se precisar de nós, estamos sempre no WhatsApp.</span>')
    )
    html = _email_wrapper('Última chance para seu carrinho', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Não deixe escapar — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_3_enviado = True
        carrinho.save(update_fields=['email_abandono_3_enviado', 'atualizado_em'])
    return ok


# ── WHATSAPP: NOTIFICAÇÃO DE NOVO PEDIDO ──────────────────────────
def _enviar_whatsapp_admin(mensagem):
    """Helper interno: envia mensagem ao admin.

    Prefere Evolution API (WHATSAPP_API_URL + WHATSAPP_API_KEY). Cai em
    CallMeBot quando Evolution nao esta configurada ou falha. Nunca propaga erro.
    """
    whatsapp_phone = os.environ.get('WHATSAPP_ADMIN_PHONE', '5511913225256').strip()

    # 1) Evolution API (preferida, sem TOS fragil do CallMeBot).
    if os.environ.get('WHATSAPP_API_URL', '').strip() and os.environ.get('WHATSAPP_API_KEY', '').strip():
        try:
            from ..whatsapp import enviar_whatsapp
            resultado = enviar_whatsapp(whatsapp_phone, mensagem)
            if resultado.get('ok'):
                return True
            logger.warning('[WHATSAPP] Evolution falhou; tentando CallMeBot. detalhe=%s', resultado.get('body', '')[:200])
        except Exception as exc:
            logger.warning('[WHATSAPP] Erro Evolution; tentando CallMeBot. erro=%s', exc)

    # 2) Fallback CallMeBot.
    try:
        callmebot_key = os.environ.get('CALLMEBOT_API_KEY', '').strip()
        if not callmebot_key:
            logger.warning('CALLMEBOT_API_KEY nao configurada. Alerta WhatsApp ignorado.')
            return False
        http_requests.get(
            'https://api.callmebot.com/whatsapp.php',
            params={'phone': whatsapp_phone, 'text': mensagem, 'apikey': callmebot_key},
            timeout=10,
        )
        return True
    except Exception:
        logger.debug('[WHATSAPP] CallMeBot silencioso (nao quebra fluxo).', exc_info=True)
        return False


def enviar_whatsapp_pedido(pedido):
    """Envia notificação no WhatsApp quando chegar um novo pedido."""
    painel_url = site_url(f'/painel/loja/pedido/{pedido.id}/change/')
    mensagem = (
        f"Novo pedido #{pedido.id}\n\n"
        f"Total: R$ {pedido.total}\n"
        f"Status: {pedido.get_status_display()}\n"
        f"Ver no painel: {painel_url}"
    )
    _enviar_whatsapp_admin(mensagem)


def enviar_whatsapp_alerta_melhor_envio(pedido, erro_texto):
    """Alerta urgente: pedido pago mas Melhor Envio nao criou etiqueta."""
    painel_url = site_url(f'/painel/loja/pedido/{pedido.id}/change/')
    resumo_erro = (erro_texto or '')[:200]
    mensagem = (
        f"[URGENTE] Melhor Envio FALHOU no pedido #{pedido.id}\n\n"
        f"Cliente pagou mas etiqueta nao foi gerada.\n"
        f"Total: R$ {pedido.total}\n"
        f"Erro: {resumo_erro}\n\n"
        f"Painel: {painel_url}"
    )
    _enviar_whatsapp_admin(mensagem)
