"""Punto de entrada serverless para Vercel (Python runtime): expone la app ASGI de FastAPI."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, bootstrap_admin  # noqa: E402

# En serverless no se garantiza el evento "lifespan": crea el superadmin (idempotente) en cada arranque en frío.
try:
    bootstrap_admin()
except Exception:  # p. ej. variables o BD aún sin configurar: no debe tumbar la función
    logging.getLogger("crm").exception("bootstrap_admin falló")
