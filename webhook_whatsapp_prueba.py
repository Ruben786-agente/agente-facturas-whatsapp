# -*- coding: utf-8 -*-
"""
Versión MÍNIMA del webhook de WhatsApp, para la primera prueba en internet.
No toca base de datos ni nada más -- solo confirma que Meta consigue
verificar y mandar mensajes a tu servidor. Cuando esto funcione, se sustituye
por webhook_whatsapp.py (la versión completa, ya conectada al pipeline).
"""

import os
import hashlib
import hmac
import logging

from flask import Flask, request, abort

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("webhook_prueba")

app = Flask(__name__)


@app.route("/webhook/whatsapp", methods=["GET"])
def verificar():
    if (request.args.get("hub.mode") == "subscribe"
            and request.args.get("hub.verify_token") == os.environ["WHATSAPP_VERIFY_TOKEN"]):
        return request.args.get("hub.challenge"), 200
    return "Verificación fallida", 403


@app.route("/webhook/whatsapp", methods=["POST"])
def recibir():
    firma = request.headers.get("X-Hub-Signature-256", "")
    secreto = os.environ["WHATSAPP_APP_SECRET"].encode()
    esperado = "sha256=" + hmac.new(secreto, request.get_data(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, firma):
        abort(403)

    log.info("Mensaje recibido de WhatsApp: %s", request.get_json(force=True))
    return "OK", 200


@app.route("/")
def home():
    return "Servidor funcionando correctamente."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
