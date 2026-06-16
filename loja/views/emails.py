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


def _imagem_thumb_email(produto, w=96, h=96):
    """Aplica transformacao Cloudinary inline para thumbnails de email.

    Cloudinary aceita transformacoes na URL: /upload/<params>/v.../arquivo.jpg
    Aqui evitamos baixar imagens originais (2MB+) dentro de emails — clientes
    como Outlook/Gmail bloqueiam imagens pesadas e atrasam o render.
    """
    if not getattr(produto, 'imagem', None):
        return ''
    url = produto.imagem.url
    if '/upload/' in url:
        return url.replace('/upload/', f'/upload/c_fill,w_{w},h_{h},q_auto,f_auto/', 1)
    return url


def enfileirar_email_pendente(payload, motivo='', pedido_id=None, tipo=''):
    destinatarios = payload.get('to') or [{}]
    destinatario = destinatarios[0] if destinatarios else {}
    if pedido_id and tipo:
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


# ── HELPERS DE INFRAESTRUTURA ──────────────────────────────────────
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


def _brevo_payload(destinatario_email, destinatario_nome, assunto, html):
    return {
        'sender': _brevo_sender(),
        'to': [{'email': destinatario_email, 'name': destinatario_nome}],
        'subject': assunto,
        'htmlContent': html,
    }


# ── HELPERS DE DESIGN ──────────────────────────────────────────────
def _paragrafo(texto):
    return f'<p style="font-size:14px;color:#4A4038;line-height:1.7;margin:0 0 12px">{texto}</p>'


def _email_icon(nome='gem', size=22, color='#6B7A64'):
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


def _btn(texto, url, cor='#6B7A64'):
    return (
        f'<a href="{url}" style="display:inline-block;padding:13px 32px;background:{cor};'
        f'color:#FFFFFF;border-radius:999px;text-decoration:none;font-size:12px;font-weight:700;'
        f'letter-spacing:0.08em;text-transform:uppercase;max-width:220px">{texto}</a>'
    )


def _timeline_pedido(etapa_atual=0):
    """Linha do tempo do pedido compatível com Outlook/Gmail/Apple Mail."""
    etapas = ['Confirmado', 'Em preparo', 'Enviado', 'Entregue']
    circles_html = ''
    labels_html = ''

    for i, nome in enumerate(etapas):
        done = i < etapa_atual
        active = i == etapa_atual

        if done:
            bg, symbol, text_col, fw = '#6B7A64', '&#10003;', '#4A4038', '700'
        elif active:
            bg, symbol, text_col, fw = '#C8A96A', '&#9679;', '#4A4038', '700'
        else:
            bg, symbol, text_col, fw = '#E8E3D8', '&nbsp;', '#8A8178', '500'

        circles_html += (
            f'<td style="text-align:center;padding:0 2px">'
            f'<span style="display:inline-block;width:26px;height:26px;border-radius:50%;'
            f'background:{bg};line-height:26px;text-align:center;font-size:11px;'
            f'color:#FFFFFF;font-weight:700">{symbol}</span>'
            f'</td>'
        )
        labels_html += (
            f'<td style="text-align:center;padding:6px 2px 0">'
            f'<span style="font-size:10px;font-weight:{fw};color:{text_col};'
            f'letter-spacing:0.04em;text-transform:uppercase">{nome}</span>'
            f'</td>'
        )

        if i < len(etapas) - 1:
            line_col = '#6B7A64' if done else '#E8E3D8'
            circles_html += (
                f'<td style="padding-bottom:13px">'
                f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
                f'<tr><td style="border-bottom:1px solid {line_col};font-size:0;line-height:0">&nbsp;</td></tr>'
                f'</table></td>'
            )
            labels_html += '<td></td>'

    return (
        '<div style="background:#FAFAF7;border:1px solid #E8E3D8;border-radius:14px;padding:18px 16px;margin:16px 0">'
        '<p style="margin:0 0 14px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase;text-align:center">Status do pedido</p>'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>{circles_html}</tr><tr>{labels_html}</tr></table>'
        '</div>'
    )


def _email_pedido_resumo(pedido):
    """Card compacto: primeiro produto + +N itens se houver mais."""
    todos_itens = list(pedido.itens.select_related('produto').all())
    if not todos_itens:
        return ''
    primeiro = todos_itens[0]
    restantes = len(todos_itens) - 1
    mais_itens = (
        f'<p style="margin:8px 0 0;color:#8A8178;font-size:12px">+{restantes} {"item" if restantes == 1 else "itens"}</p>'
        if restantes > 0 else ''
    )
    return (
        '<div style="background:#FAFAF7;border:1px solid #E8E3D8;border-radius:14px;padding:16px 20px;margin:16px 0">'
        f'<p style="margin:0 0 10px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Pedido #{pedido.id}</p>'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        '<tr>'
        f'<td style="color:#4A4038;font-size:14px;font-weight:600;line-height:1.4">{primeiro.nome_produto}</td>'
        f'<td style="color:#8A8178;font-size:13px;text-align:center;width:36px">&times;{primeiro.quantidade}</td>'
        f'<td style="color:#6B7A64;font-size:14px;font-weight:700;text-align:right;white-space:nowrap">R$&nbsp;{primeiro.preco_unitario}</td>'
        '</tr>'
        '</table>'
        f'{mais_itens}'
        '</div>'
    )


def _card_financeiro(pedido):
    """Card minimalista com subtotal, frete, desconto e total em destaque."""
    frete_texto = 'Gr&aacute;tis' if pedido.frete == 0 else f'R$&nbsp;{pedido.frete}'
    desconto_row = ''
    if pedido.desconto > 0:
        cupom = pedido.cupom_codigo or ''
        desconto_row = (
            f'<tr>'
            f'<td style="padding:4px 0;color:#8A8178;font-size:12px">Desconto {cupom}</td>'
            f'<td style="padding:4px 0;color:#6B7A64;font-size:12px;text-align:right">&minus;&nbsp;R$&nbsp;{pedido.desconto}</td>'
            f'</tr>'
        )
    return (
        '<div style="background:#FAFAF7;border:1px solid #E8E3D8;border-radius:14px;padding:16px 20px;margin:16px 0">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">'
        f'<tr><td style="padding:4px 0;color:#8A8178;font-size:12px">Subtotal</td>'
        f'<td style="padding:4px 0;color:#4A4038;font-size:12px;text-align:right">R$&nbsp;{pedido.subtotal}</td></tr>'
        f'<tr><td style="padding:4px 0;color:#8A8178;font-size:12px">Frete</td>'
        f'<td style="padding:4px 0;color:#4A4038;font-size:12px;text-align:right">{frete_texto}</td></tr>'
        f'{desconto_row}'
        f'<tr><td style="padding:12px 0 0;border-top:1px solid #E8E3D8;color:#4A4038;font-size:15px;font-weight:700">Total</td>'
        f'<td style="padding:12px 0 0;border-top:1px solid #E8E3D8;text-align:right;'
        f'color:#6B7A64;font-size:18px;font-weight:800">R$&nbsp;{pedido.total}</td></tr>'
        '</table>'
        '</div>'
    )


def _email_entrega(pedido):
    """Card de entrega compacto em 2 linhas."""
    linha1 = f'{pedido.rua}, {pedido.numero}'
    if pedido.complemento:
        linha1 += f' &mdash; {pedido.complemento}'
    linha2 = f'{pedido.bairro}, {pedido.cidade}/{pedido.estado} &middot; CEP {pedido.cep}'
    return (
        '<div style="background:#F5F2EC;border-radius:12px;padding:14px 18px;margin:16px 0">'
        '<p style="margin:0 0 6px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Entrega</p>'
        f'<p style="margin:0;color:#4A4038;font-size:13px;line-height:1.7">{linha1}<br>{linha2}</p>'
        '</div>'
    )


def _email_wrapper(titulo, corpo_html, preheader=''):
    preheader_html = preheader or titulo
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    @media only screen and (max-width: 600px) {{
      .ew-outer {{ padding: 0 !important; }}
      .ew-shell {{ width: 100% !important; border-radius: 0 !important; }}
      .ew-pad {{ padding-left: 20px !important; padding-right: 20px !important; }}
      .ew-title {{ font-size: 22px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#F5F2EC;font-family:Montserrat,Arial,sans-serif">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;font-size:1px;color:transparent">{preheader_html}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#F5F2EC">
    <tr>
      <td class="ew-outer" align="center" style="padding:20px 12px">
        <table role="presentation" class="ew-shell" width="540" cellspacing="0" cellpadding="0" border="0"
          style="width:540px;max-width:540px;background:#FFFFFF;border-radius:20px;overflow:hidden;
                 border:1px solid #E8E3D8;box-shadow:0 8px 40px rgba(74,64,56,0.10)">

          <!-- HEADER COMPACTO -->
          <tr>
            <td style="background:#6B7A64;padding:20px 32px;text-align:center">
              <img src="{EMAIL_LOGO_URL}" width="52" height="52" alt="{EMAIL_BRAND_NAME}"
                style="display:block;margin:0 auto 10px;border-radius:50%;border:2px solid rgba(255,255,255,0.35)">
              <span style="display:block;color:#FFFFFF;font-family:Georgia,'Times New Roman',serif;
                           font-size:17px;font-weight:700;letter-spacing:0.06em">{EMAIL_BRAND_NAME}</span>
              <span style="display:block;margin:6px auto 0;width:32px;height:1px;background:rgba(200,169,106,0.70);font-size:0"></span>
            </td>
          </tr>

          <!-- TÍTULO -->
          <tr>
            <td class="ew-pad" style="padding:26px 36px 6px;text-align:center">
              <h1 class="ew-title"
                style="margin:0;color:#4A4038;font-family:'Playfair Display',Georgia,'Times New Roman',serif;
                       font-size:24px;font-weight:700;line-height:1.25;letter-spacing:-0.01em">{titulo}</h1>
            </td>
          </tr>

          <!-- CORPO -->
          <tr>
            <td class="ew-pad" style="padding:12px 36px 28px">{corpo_html}</td>
          </tr>

          <!-- RODAPÉ -->
          <tr>
            <td style="background:#F5F2EC;border-top:1px solid #E8E3D8;padding:14px 36px;text-align:center">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center">
                <tr>
                  <td style="padding:0 8px">
                    <a href="https://wa.me/5511913225256"
                       style="color:#6B7A64;text-decoration:none;font-size:12px;font-weight:600">WhatsApp</a>
                  </td>
                  <td style="color:#C8A96A;font-size:12px">&middot;</td>
                  <td style="padding:0 8px">
                    <a href="https://www.barrsstore.com.br"
                       style="color:#6B7A64;text-decoration:none;font-size:12px;font-weight:600">Site</a>
                  </td>
                  <td style="color:#C8A96A;font-size:12px">&middot;</td>
                  <td style="padding:0 8px">
                    <a href="https://www.instagram.com/barrsstore"
                       style="color:#6B7A64;text-decoration:none;font-size:12px;font-weight:600">Instagram</a>
                  </td>
                </tr>
              </table>
              <p style="margin:7px 0 0;color:#8A8178;font-size:11px">&copy; 2026 Barrs Store</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ── E-MAILS TRANSACIONAIS ──────────────────────────────────────────

def enviar_email_confirmacao(pedido):
    """E-mail premium de confirmação de pedido via Brevo."""
    try:
        link_acompanhar = site_url(reverse('rastrear_pedido'))
        subtitulo = '<p style="margin:0 0 16px;color:#8A8178;font-size:14px;text-align:center;line-height:1.6">Recebemos seu pagamento e j&aacute; estamos preparando tudo com carinho.</p>'
        corpo = (
            subtitulo
            + _email_pedido_resumo(pedido)
            + _card_financeiro(pedido)
            + _email_entrega(pedido)
            + _timeline_pedido(0)
            + f'<div style="text-align:center;margin:24px 0">{_btn("Acompanhar pedido", link_acompanhar)}</div>'
        )
        html = _email_wrapper('Seu pedido foi confirmado &#10024;', corpo, f'Pedido #{pedido.id} confirmado &middot; R$ {pedido.total}')
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


def enviar_email_conta_criada(pedido, senha):
    """Email imediato quando conta é criada automaticamente no checkout sem senha."""
    try:
        link_minha_conta = site_url(reverse('minha_conta'))
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        primeiro_nome = pedido.nome.split()[0]

        card_senha = (
            '<div style="background:#FAFAF7;border:2px solid #C8A96A;border-radius:14px;'
            'padding:18px 24px;margin:20px 0;text-align:center">'
            '<p style="margin:0 0 6px;color:#8A8178;font-size:10px;font-weight:700;'
            'letter-spacing:0.14em;text-transform:uppercase">Sua conta foi criada automaticamente</p>'
            f'<p style="margin:0 0 4px;color:#4A4038;font-size:22px;font-weight:800;'
            f'letter-spacing:0.08em;font-family:monospace">{senha}</p>'
            '<p style="margin:6px 0 0;color:#8A8178;font-size:12px">'
            'Voc&ecirc; pode alter&aacute;-la depois em Minha Conta</p>'
            '</div>'
        )
        corpo = (
            _paragrafo(f'Ol&aacute;, <strong style="color:#4A4038">{primeiro_nome}</strong>! '
                       'Seu pedido foi criado com sucesso.')
            + card_senha
            + _email_pedido_resumo(pedido)
            + f'<div style="text-align:center;margin:20px 0">'
            f'{_btn("Finalizar pagamento", link_pagamento, "#C8A96A")}'
            f'&nbsp;&nbsp;'
            f'{_btn("Minha conta", link_minha_conta)}'
            f'</div>'
            + _paragrafo(
                '<span style="color:#8A8178;font-size:13px">'
                'Guarde sua senha em lugar seguro. D&uacute;vidas? Estamos no WhatsApp.'
                '</span>'
            )
        )
        html = _email_wrapper(
            'Sua conta foi criada &#10024;',
            corpo,
            f'Pedido #{pedido.id} criado &middot; sua senha de acesso est&aacute; aqui',
        )
        payload = _brevo_payload(
            pedido.email,
            pedido.nome,
            f'Sua conta na Barrs Store foi criada — pedido #{pedido.id}',
            html,
        )
        ok, erro, resposta = enviar_brevo_payload(payload)
        if not ok:
            enfileirar_email_pendente(payload, erro, pedido_id=pedido.id, tipo='conta_criada')
            logger.warning('[BREVO] Email conta_criada pedido %s enfileirado. erro=%s', pedido.id, erro)
            return False
        logger.info('[BREVO] Email conta_criada pedido %s enviado.', pedido.id)
        return True
    except Exception as exc:
        logger.exception('Erro ao enviar email conta_criada pedido %s: %s', pedido.id, exc)
        return False


def enviar_email_pagamento_pendente(pedido):
    """Lembrete de pagamento pendente."""
    if pedido.email_pagamento_pendente_enviado:
        return True
    try:
        link_pagamento = site_url(reverse('confirmacao', kwargs={'pedido_id': pedido.id, 'token': pedido.access_token}))
        corpo = (
            '<p style="margin:0 0 16px;color:#8A8178;font-size:14px;text-align:center;line-height:1.6">'
            'Seu pedido foi reservado e est&aacute; aguardando a finaliza&ccedil;&atilde;o do pagamento.'
            '</p>'
            + _email_pedido_resumo(pedido)
            + _card_financeiro(pedido)
            + f'<div style="text-align:center;margin:24px 0">{_btn("Finalizar pagamento", link_pagamento, "#C8A96A")}</div>'
            + _paragrafo('<span style="color:#8A8178;font-size:13px">Se voc&ecirc; j&aacute; pagou, pode ignorar este e-mail. A confirma&ccedil;&atilde;o acontece automaticamente assim que o pagamento for aprovado.</span>')
        )
        html = _email_wrapper('Seu pedido est&aacute; reservado', corpo, f'Finalize o pagamento do pedido #{pedido.id}.')
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
    """Envia o código de rastreio ao cliente quando o pedido for enviado."""
    if not pedido.codigo_rastreio:
        return False
    try:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        card_rastreio = (
            '<div style="background:#FAFAF7;border:1px solid #E8E3D8;border-radius:14px;padding:16px 20px;margin:16px 0;text-align:center">'
            '<p style="margin:0 0 6px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">C&oacute;digo de rastreio</p>'
            f'<p style="margin:0 0 4px;color:#4A4038;font-size:18px;font-weight:700;letter-spacing:0.06em">{pedido.codigo_rastreio}</p>'
            f'<p style="margin:0;color:#8A8178;font-size:12px">{transportadora}</p>'
            '</div>'
        )
        corpo = (
            '<p style="margin:0 0 16px;color:#8A8178;font-size:14px;text-align:center;line-height:1.6">'
            f'Seu pedido #{pedido.id} acaba de sair para entrega.'
            '</p>'
            + card_rastreio
            + _email_pedido_resumo(pedido)
            + _timeline_pedido(2)
            + f'<div style="text-align:center;margin:24px 0">{_btn("Acompanhar entrega", rastreio_url)}</div>'
            + _paragrafo(f'<span style="color:#8A8178;font-size:12px">Caso o bot&atilde;o n&atilde;o abra, acesse: <a href="{rastreio_url}" style="color:#6B7A64;text-decoration:none">{rastreio_url}</a></span>')
        )
        html = _email_wrapper('Seu pedido foi enviado &#128666;', corpo, f'C&oacute;digo de rastreio do pedido #{pedido.id}: {pedido.codigo_rastreio}.')
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


# ── SEQUÊNCIA PÓS-COMPRA ──────────────────────────────────────────

def _enviar_poscompra(pedido, etapa, assunto, html):
    ok = _brevo_send(assunto, html, pedido.email, pedido.nome)
    if ok:
        flag = f'email_poscompra_{etapa}_enviado'
        setattr(pedido, flag, True)
        pedido.save(update_fields=[flag])
    return ok


def enviar_email_poscompra_1(pedido):
    """E-mail 1 (~1h): pedido em preparo."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    primeiro_nome = pedido.nome.split()[0]
    corpo = (
        _paragrafo(f'Oi, <strong style="color:#4A4038">{primeiro_nome}</strong>! Que alegria receber seu pedido.')
        + _paragrafo('J&aacute; estamos separando cada pe&ccedil;a com cuidado para garantir que chegue at&eacute; voc&ecirc; perfeita. Da embalagem &agrave; entrega, cada detalhe importa.')
        + _email_pedido_resumo(pedido)
        + _timeline_pedido(1)
        + f'<div style="text-align:center;margin:24px 0">{_btn("Acompanhar meu pedido", link_rastrear)}</div>'
        + _paragrafo('<span style="color:#8A8178;font-size:13px">Em breve voc&ecirc; receber&aacute; o c&oacute;digo de rastreio. D&uacute;vidas? Estamos no WhatsApp.</span>')
    )
    return _enviar_poscompra(
        pedido, 1,
        f'Seu pedido #{pedido.id} está sendo preparado — Barrs Store',
        _email_wrapper('Seu pedido est&aacute; em boas m&atilde;os &#10024;', corpo),
    )


def enviar_email_poscompra_2(pedido):
    """E-mail 2 (~24h): bastidores da marca."""
    link_loja = site_url('/')
    primeiro_nome = pedido.nome.split()[0]
    dica = (
        '<div style="background:#F5F2EC;border-radius:12px;padding:16px 18px;margin:16px 0">'
        '<p style="margin:0 0 8px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Dica de cuidado</p>'
        + _paragrafo('Guarde suas pe&ccedil;as em local seco, longe de perfumes e produtos qu&iacute;micos. Para an&eacute;is e pulseiras, evite contato com &aacute;gua. Assim, elas duram muito mais.')
        + '</div>'
    )
    corpo = (
        _paragrafo(f'<strong style="color:#4A4038">{primeiro_nome}</strong>, enquanto preparamos seu pedido com carinho, quer&iacute;amos te contar como trabalhamos por aqui.')
        + _paragrafo('Cada pe&ccedil;a da Barrs Store passa por uma curadoria criteriosa. Acreditamos que um acess&oacute;rio bem escolhido &eacute; uma extens&atilde;o da sua personalidade.')
        + dica
        + f'<div style="text-align:center;margin:20px 0">{_btn("Ver novidades na loja", link_loja)}</div>'
    )
    return _enviar_poscompra(
        pedido, 2,
        f'Um cuidado especial sobre seu pedido #{pedido.id} — Barrs Store',
        _email_wrapper('O cuidado que vai junto com cada pe&ccedil;a', corpo),
    )


def enviar_email_poscompra_3(pedido):
    """E-mail 3 (~3 dias): atualização de envio."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    primeiro_nome = pedido.nome.split()[0]

    if pedido.codigo_rastreio:
        rastreio_url = pedido.rastreio_url()
        transportadora = pedido.rastreio_transportadora()
        trecho = (
            '<div style="background:#FAFAF7;border:1px solid #E8E3D8;border-radius:14px;padding:16px 20px;margin:16px 0;text-align:center">'
            '<p style="margin:0 0 6px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">C&oacute;digo de rastreio</p>'
            f'<p style="margin:0 0 4px;color:#4A4038;font-size:18px;font-weight:700;letter-spacing:0.06em">{pedido.codigo_rastreio}</p>'
            f'<p style="margin:0;color:#8A8178;font-size:12px">{transportadora}</p>'
            '</div>'
            + f'<div style="text-align:center;margin:20px 0">{_btn("Rastrear minha encomenda", rastreio_url)}</div>'
        )
        titulo = 'Seu pedido saiu para entrega &#128666;'
        intro = _paragrafo(f'<strong style="color:#4A4038">{primeiro_nome}</strong>, &oacute;tima not&iacute;cia! Seu pedido #{pedido.id} foi enviado e j&aacute; est&aacute; a caminho.')
    else:
        trecho = (
            _paragrafo('Estamos finalizando o preparo e em breve ele sair&aacute; para entrega. Voc&ecirc; receber&aacute; o c&oacute;digo de rastreio assim que for despachado.')
            + f'<div style="text-align:center;margin:20px 0">{_btn("Rastrear pedido", link_rastrear)}</div>'
        )
        titulo = 'Seu pedido est&aacute; quase pronto &#10024;'
        intro = _paragrafo(f'<strong style="color:#4A4038">{primeiro_nome}</strong>, o pedido #{pedido.id} est&aacute; nos &uacute;ltimos detalhes de preparo!')

    corpo = (
        intro
        + trecho
        + _paragrafo('<span style="color:#8A8178;font-size:13px">Qualquer d&uacute;vida, estamos no WhatsApp. Mal podemos esperar para voc&ecirc; receber suas pe&ccedil;as.</span>')
    )
    return _enviar_poscompra(
        pedido, 3,
        f'Atualização do seu pedido #{pedido.id} — Barrs Store',
        _email_wrapper(titulo, corpo),
    )


def enviar_email_poscompra_4(pedido):
    """E-mail 4 (~7 dias): verificação pós-entrega estimada."""
    link_rastrear = site_url(reverse('rastrear_pedido'))
    link_wa = 'https://wa.me/5511913225256'
    primeiro_nome = pedido.nome.split()[0]
    corpo = (
        _paragrafo(f'<strong style="color:#4A4038">{primeiro_nome}</strong>, j&aacute; faz alguns dias desde que enviamos seu pedido. Chegou tudo certinho?')
        + _paragrafo('Adorar&iacute;amos saber como est&aacute; sendo a experi&ecirc;ncia com suas novas pe&ccedil;as. Se tiver qualquer d&uacute;vida sobre a entrega, estamos aqui.')
        + '<table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:22px auto">'
        + '<tr>'
        + f'<td style="padding-right:10px"><a href="{link_wa}" style="display:inline-block;padding:12px 22px;background:#25D366;color:#FFFFFF;border-radius:999px;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase">WhatsApp</a></td>'
        + f'<td><a href="{link_rastrear}" style="display:inline-block;padding:12px 22px;background:#F5F2EC;color:#4A4038;border:1px solid #D9D3C7;border-radius:999px;text-decoration:none;font-size:12px;font-weight:600;letter-spacing:0.04em;text-transform:uppercase">Rastrear pedido</a></td>'
        + '</tr>'
        + '</table>'
        + _paragrafo('<span style="color:#8A8178;font-size:13px">Sua satisfa&ccedil;&atilde;o &eacute; o que nos move a continuar criando pe&ccedil;as com tanto cuidado.</span>')
    )
    return _enviar_poscompra(
        pedido, 4,
        f'Tudo certo com seu pedido #{pedido.id}? — Barrs Store',
        _email_wrapper('Chegou tudo bem? &#128149;', corpo),
    )


def enviar_email_poscompra_5(pedido):
    """E-mail 5 (~15 dias): fidelização."""
    link_loja = site_url('/')
    link_wa = 'https://wa.me/5511913225256'
    primeiro_nome = pedido.nome.split()[0]
    card_instagram = (
        '<div style="background:#F5F2EC;border-radius:12px;padding:18px 20px;margin:16px 0;text-align:center">'
        + '<p style="margin:0 0 8px;color:#4A4038;font-size:13px;font-weight:600">Novidades chegando todo m&ecirc;s</p>'
        + _paragrafo('<span style="font-size:13px;color:#8A8178">Acompanhe no Instagram e seja a primeira a saber dos lan&ccedil;amentos exclusivos.</span>')
        + '<a href="https://www.instagram.com/barrsstore" style="display:inline-block;padding:10px 22px;background:#6B7A64;color:#FFFFFF;border-radius:999px;text-decoration:none;font-size:12px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase">@barrsstore</a>'
        + '</div>'
    )
    corpo = (
        _paragrafo(f'<strong style="color:#4A4038">{primeiro_nome}</strong>, obrigada de verdade por escolher a Barrs Store.')
        + _paragrafo('Clientes como voc&ecirc; s&atilde;o a raz&atilde;o de cada detalhe que dedicamos &mdash; da curadoria &agrave; embalagem.')
        + card_instagram
        + f'<div style="text-align:center;margin:18px 0">{_btn("Ver novas pe&ccedil;as", link_loja)}</div>'
        + _paragrafo(f'<span style="color:#8A8178;font-size:13px">Tem alguma pe&ccedil;a dos sonhos? Me conta pelo <a href="{link_wa}" style="color:#6B7A64;text-decoration:none">WhatsApp</a>.</span>')
    )
    return _enviar_poscompra(
        pedido, 5,
        f'Obrigada, {primeiro_nome} — Barrs Store',
        _email_wrapper('Uma mensagem especial para voc&ecirc; &#10024;', corpo),
    )


# ── SEQUÊNCIA ABANDONO DE CARRINHO ────────────────────────────────

def enviar_email_abandono_1(carrinho):
    """E-mail 1 (~1h): primeiro contato suave."""
    if not carrinho.email_cliente:
        return False
    link_checkout = carrinho.link_checkout()
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False

    itens_html = ''
    for item in itens:
        img = (
            f'<img src="{_imagem_thumb_email(item.produto, 96, 96)}" alt="{item.produto.nome}" width="48" height="48" style="border-radius:8px;display:block;object-fit:cover">'
            if item.produto.imagem else
            f'<div style="width:48px;height:48px;border-radius:8px;background:#E8E3D8;text-align:center;line-height:48px">{_email_icon("gem", 20)}</div>'
        )
        tamanho = f'<p style="font-size:11px;color:#8A8178;margin:2px 0 0">Tamanho: {item.tamanho}</p>' if item.tamanho else ''
        itens_html += (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-bottom:10px">'
            '<tr>'
            f'<td width="56" valign="top">{img}</td>'
            f'<td style="padding-left:12px"><p style="font-size:13px;font-weight:600;color:#4A4038;margin:0">{item.produto.nome}</p>{tamanho}</td>'
            f'<td style="font-size:14px;font-weight:700;color:#6B7A64;white-space:nowrap;padding-left:8px" valign="top">R$&nbsp;{item.subtotal()}</td>'
            '</tr>'
            '</table>'
        )

    corpo = (
        _paragrafo('Voc&ecirc; deixou algumas pe&ccedil;as especiais no carrinho.')
        + f'<div style="background:#F5F2EC;border-radius:12px;padding:16px 18px;margin:16px 0">{itens_html}</div>'
        + f'<div style="text-align:center;margin:22px 0">{_btn("Finalizar minha compra", link_checkout)}</div>'
        + _paragrafo('<span style="color:#8A8178;font-size:13px">D&uacute;vida sobre tamanho ou entrega? Estamos no WhatsApp.</span>')
    )
    html = _email_wrapper('Voc&ecirc; esqueceu algo especial &#128149;', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Seu carrinho ainda está aqui — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_1_enviado = True
        carrinho.save(update_fields=['email_abandono_1_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_2(carrinho):
    """E-mail 2 (~24h): destaca benefícios."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()
    total = carrinho.total()

    beneficios = (
        '<div style="background:#F5F2EC;border-radius:12px;padding:16px 18px;margin:16px 0">'
        '<p style="margin:0 0 10px;color:#8A8178;font-size:10px;font-weight:700;letter-spacing:0.14em;text-transform:uppercase">Por que comprar na Barrs Store</p>'
        + _paragrafo(f'{_email_icon("truck", 14)} &nbsp;Entrega para todo o Brasil')
        + _paragrafo(f'{_email_icon("gem", 14)} &nbsp;Semij&oacute;ias com acabamento premium')
        + _paragrafo(f'{_email_icon("message", 14)} &nbsp;Atendimento humanizado via WhatsApp')
        + '</div>'
    )
    corpo = (
        _paragrafo('Suas pe&ccedil;as ainda est&atilde;o esperando por voc&ecirc;.')
        + beneficios
        + f'<p style="margin:14px 0;color:#4A4038;font-size:15px;font-weight:600">Total do carrinho: <span style="color:#6B7A64">R$&nbsp;{total}</span></p>'
        + f'<div style="text-align:center;margin:22px 0">{_btn("Garantir meu pedido agora", link_checkout)}</div>'
    )
    html = _email_wrapper('Suas pe&ccedil;as est&atilde;o esperando por voc&ecirc; &#10024;', corpo)
    nome = carrinho.email_cliente.split('@')[0].capitalize()
    ok = _brevo_send('Ainda dá tempo — seu carrinho está salvo — Barrs Store', html, carrinho.email_cliente, nome)
    if ok:
        carrinho.email_abandono_2_enviado = True
        carrinho.save(update_fields=['email_abandono_2_enviado', 'atualizado_em'])
    return ok


def enviar_email_abandono_3(carrinho):
    """E-mail 3 (~48h): urgência suave, última mensagem."""
    if not carrinho.email_cliente:
        return False
    itens = carrinho.itens.select_related('produto').all()
    if not itens:
        return False
    link_checkout = carrinho.link_checkout()
    qtd = sum(i.quantidade for i in itens)

    card_resumo = (
        '<div style="background:#F5F2EC;border:1px solid #E8E3D8;border-radius:12px;padding:16px 18px;margin:16px 0;text-align:center">'
        f'<p style="margin:0 0 4px;color:#4A4038;font-size:13px">Voc&ecirc; tem <strong>{qtd} pe&ccedil;{"a" if qtd == 1 else "as"}</strong> reservada{"" if qtd == 1 else "s"}</p>'
        f'<p style="margin:0;color:#6B7A64;font-size:20px;font-weight:800">R$&nbsp;{carrinho.total()}</p>'
        '</div>'
    )
    corpo = (
        _paragrafo('Esta &eacute; nossa &uacute;ltima mensagem sobre seu carrinho &mdash; prometemos.')
        + _paragrafo('Os estoques da Barrs Store s&atilde;o limitados. N&atilde;o queremos que voc&ecirc; perca as pe&ccedil;as que escolheu.')
        + card_resumo
        + f'<div style="text-align:center;margin:22px 0">{_btn("Finalizar antes que esgote", link_checkout, "#C8A96A")}</div>'
        + _paragrafo('<span style="color:#8A8178;font-size:12px">Se mudou de ideia, sem problema. Mas se precisar de n&oacute;s, estamos no WhatsApp.</span>')
    )
    html = _email_wrapper('&Uacute;ltima chance para seu carrinho', corpo)
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
    whatsapp_phone = os.environ.get('WHATSAPP_ADMIN_PHONE', '5511978801001').strip()

    if os.environ.get('WHATSAPP_API_URL', '').strip() and os.environ.get('WHATSAPP_API_KEY', '').strip():
        try:
            from ..whatsapp import enviar_whatsapp
            resultado = enviar_whatsapp(whatsapp_phone, mensagem)
            if resultado.get('ok'):
                return True
            logger.warning('[WHATSAPP] Evolution falhou; tentando CallMeBot. detalhe=%s', resultado.get('body', '')[:200])
        except Exception as exc:
            logger.warning('[WHATSAPP] Erro Evolution; tentando CallMeBot. erro=%s', exc)

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

    itens = pedido.itens.select_related('produto').all()
    linhas_itens = []
    for item in itens:
        tamanho = f' (Nº {item.tamanho})' if item.tamanho else ''
        linhas_itens.append(f'  • {item.quantidade}x {item.nome_produto}{tamanho}')
    produtos_texto = '\n'.join(linhas_itens) if linhas_itens else '  (sem itens)'

    complemento = f', {pedido.complemento}' if pedido.complemento else ''
    endereco = (
        f'{pedido.rua}, {pedido.numero}{complemento}\n'
        f'  {pedido.bairro} — {pedido.cidade}/{pedido.estado}\n'
        f'  CEP: {pedido.cep}'
    )

    valores = f'Subtotal: R$ {pedido.subtotal}'
    if pedido.desconto and pedido.desconto > 0:
        valores += f'\nDesconto: -R$ {pedido.desconto}'
    if pedido.frete and pedido.frete > 0:
        valores += f'\nFrete: R$ {pedido.frete}'
    valores += f'\nTotal: R$ {pedido.total}'

    mensagem = (
        f"*Novo pedido #{pedido.id}* 🛒\n\n"
        f"*Cliente:* {pedido.nome}\n"
        f"*Pagamento:* {pedido.get_forma_pagamento_display()}\n"
        f"*Status:* {pedido.get_status_display()}\n\n"
        f"*Produtos:*\n{produtos_texto}\n\n"
        f"*Valores:*\n{valores}\n\n"
        f"*Endereço de entrega:*\n  {endereco}\n\n"
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
