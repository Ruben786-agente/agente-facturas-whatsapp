# -*- coding: utf-8 -*-
"""
Cobro de la suscripción con Stripe. Un solo plan, sin límites.

Idea general:
  1. Una gestoría nueva pulsa "Suscribirme" -> le generamos un enlace de pago
     de Stripe (Checkout) y la mandamos ahí.
  2. Ella paga con su tarjeta en la propia web de Stripe (nunca vemos ni
     tocamos el número de tarjeta, eso lo gestiona Stripe entero).
  3. Stripe nos avisa (webhook) de lo que pase: pago hecho, pago fallido,
     cancelación... y aquí activamos o desactivamos su acceso según toque.

Variables de entorno:
    STRIPE_SECRET_KEY       -- clave privada de tu cuenta Stripe
    STRIPE_PRICE_ID         -- el ID del precio/plan único, creado en el
                               panel de Stripe (Products -> tu producto -> precio)
    STRIPE_WEBHOOK_SECRET   -- para verificar que los webhooks vienen de verdad de Stripe
"""

import os
import logging

import stripe
from flask import Flask, request

from basededatos import activar_suscripcion, desactivar_suscripcion, resolver_tenant_por_stripe_customer_id

log = logging.getLogger("stripe_integracion")
app = Flask(__name__)


def _configurar():
    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]


def crear_sesion_pago(tenant_id, email_gestoria, url_exito, url_cancelacion):
    """
    Genera el enlace al que mandas a la gestoría para que pague.
    tenant_id viaja en 'client_reference_id' -- así, cuando Stripe nos avise
    del pago, sabemos a qué gestoría de NUESTRA base de datos corresponde.
    """
    _configurar()
    sesion = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": os.environ["STRIPE_PRICE_ID"], "quantity": 1}],
        customer_email=email_gestoria,
        client_reference_id=str(tenant_id),
        success_url=url_exito,
        cancel_url=url_cancelacion,
        allow_promotion_codes=True,  # muestra el campo "¿Tienes un código promocional?"
    )
    return sesion.url


@app.route("/webhook/stripe", methods=["POST"])
def webhook_stripe():
    _configurar()
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
        activar_suscripcion(
            tenant_id=tenant_id,
            stripe_customer_id=datos["customer"],
            stripe_subscription_id=datos["subscription"],
        )
        log.info("Suscripción activada para tenant %s", tenant_id)

    elif tipo in ("customer.subscription.deleted", "invoice.payment_failed"):
        tenant_id = resolver_tenant_por_stripe_customer_id(datos["customer"])
        if tenant_id:
            desactivar_suscripcion(tenant_id)
            log.info("Suscripción desactivada para tenant %s (motivo: %s)", tenant_id, tipo)

    return "OK", 200


if __name__ == "__main__":
    app.run(port=8001)
