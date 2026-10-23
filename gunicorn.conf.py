# -*- coding: utf-8 -*-
"""Configuración de gunicorn para el plan gratuito de Render (512 MB de memoria). Gunicorn la lee solo, desde la raíz del proyecto."""

workers = 1            # cada proceso carga toda la aplicación (~130 MB); con uno basta y no se agota la memoria
threads = 4            # varias peticiones a la vez dentro del mismo proceso
timeout = 120
max_requests = 1500    # el proceso se reinicia solo de vez en cuando y así no acumula memoria
max_requests_jitter = 150


def post_fork(server, worker):
    try:  # menos "arenas" de memoria entre hilos = menos fragmentación
        import ctypes
        ctypes.CDLL("libc.so.6").mallopt(-8, 2)
    except Exception:
        pass
