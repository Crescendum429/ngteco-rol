"""Logging estructurado para Solplast ERP."""
import logging
import os
import sys

_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(
    level=getattr(logging, _LEVEL, logging.INFO),
    format=_FORMAT,
    stream=sys.stdout,
)

# Silencia ruido de librerias externas
for noisy in ("httpx", "httpcore", "urllib3", "supabase", "postgrest"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("solplast")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"solplast.{name}")
