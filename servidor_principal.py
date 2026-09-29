# -*- coding: utf-8 -*-
"""
Servidor combinado para Render: recibe tanto los webhooks de WhatsApp (Meta)
como los de Stripe, en un único proceso.
"""

import os
import hashlib
import hmac
import logging

import stripe
from flask import Flask, request, abort

from basededatos import activar_suscripcion, desactivar_suscripcion, resolver_tenant_por_stripe_customer_id

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("servidor_principal")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# WhatsApp (versión de prueba: solo confirma que los mensajes llegan bien)
# ---------------------------------------------------------------------------
@app.route("/webhook/whatsapp", methods=["GET"])
def whatsapp_verificar():
    if (request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]):
        return request.args.get("hub.challenge"), 200
    return "Verificación fallida", 403


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_recibir():
    firma = request.headers.get("X-Hub-Signature-256", "")
    secreto = os.environ["WHATSAPP_APP_SECRET"].encode()
    esperado = "sha256=" + hmac.new(secreto, request.get_data(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, firma):
        abort(403)
    log.info("Mensaje recibido de WhatsApp: %s", request.get_json(force=True))
    return "OK", 200


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    payload = request.get_data()
    firma = request.headers.get("Stripe-Signature")

    try:
        evento = stripe.Webhook.construct_event(payload, firma, os.environ["STRIPE_WEBHOOK_SECRET"])
    except (ValueError, stripe.error.SignatureVerificationError):
        log.warning("Webhook de Stripe con firma inválida -- descartado")
        return "Firma inválida", 400

    tipo = evento["type"]
    datos = evento["data"]["object"]

    if tipo == "checkout.session.completed":
        tenant_id = datos["client_reference_id"]
        activar_suscripcion(tenant_id=tenant_id, stripe_customer_id=datos["customer"],
                             stripe_subscription_id=datos["subscription"])
        log.info("Suscripción activada para tenant %s", tenant_id)

    elif tipo in ("customer.subscription.deleted", "invoice.payment_failed"):
        tenant_id = resolver_tenant_por_stripe_customer_id(datos["customer"])
        if tenant_id:
            desactivar_suscripcion(tenant_id)
            log.info("Suscripción desactivada para tenant %s (%s)", tenant_id, tipo)

    return "OK", 200


@app.route("/")
def home():
    return "Servidor funcionando correctamente."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
