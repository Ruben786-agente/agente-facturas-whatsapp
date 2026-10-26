# -*- coding: utf-8 -*-
"""
Servidor único para Render: une el webhook de WhatsApp (completo, conectado
a la IA/OneDrive/base de datos), el webhook de Stripe, y el panel web de
cada gestoría -- los tres en un solo proceso, mediante Blueprints de Flask.
"""

import os
import logging

import stripe
from flask import Flask, request

from basededatos import activar_suscripcion, desactivar_suscripcion, resolver_tenant_por_stripe_customer_id
from webhook_whatsapp import bp_whatsapp
from panel_web import bp_panel
from alta_web import bp_alta
from tareas_web import bp_tareas
from revision_web import bp_revision
from publico_web import bp_publico
from subida_web import bp_subida
from archivos_web import bp_archivos

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("servidor_principal")

from basededatos import GestoriaNoExiste

app = Flask(__name__)
import seguridad
seguridad.iniciar(app)

app.register_blueprint(bp_whatsapp)
app.register_blueprint(bp_panel)
app.register_blueprint(bp_alta)
app.register_blueprint(bp_tareas)
app.register_blueprint(bp_revision)
app.register_blueprint(bp_publico)
app.register_blueprint(bp_subida)
app.register_blueprint(bp_archivos)


@app.errorhandler(GestoriaNoExiste)
def _sesion_huerfana(_error):
    """Sesión de una gestoría que ya no existe (p. ej. tras cambiar de base de datos): se cierra y se pide entrar de nuevo."""
    from flask import redirect, session, url_for
    session.clear()
    return redirect(url_for("panel.login"))


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
