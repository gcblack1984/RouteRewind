"""Informazioni generali dell'applicazione (un solo punto da modificare)."""
import os
import sys

APP_NAME = "RouteRewind"
APP_TAGLINE = "Ricostruzione e animazione di percorsi da file"
APP_VERSION = "1.0.0"
AUTHOR = "Giovanni Ciccarese"
COPYRIGHT = f"© 2026 {AUTHOR}"
APP_ID = "GiovanniCiccarese.RouteRewind"   # usato da Windows per l'icona nella barra

WINDOW_TITLE = f"{APP_NAME} — di {AUTHOR}"


def resource_path(*parts: str) -> str:
    """Percorso di una risorsa, valido sia da sorgente sia nell'exe PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
