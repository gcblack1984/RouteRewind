"""Informazioni generali dell'applicazione (un solo punto da modificare)."""
import os
import sys

APP_NAME = "RouteRewind"
APP_TAGLINE = "Ricostruzione e animazione di percorsi da file"
APP_VERSION = "1.0.0"
AUTHOR = "Giovanni Ciccarese"
COPYRIGHT = f"© 2026 {AUTHOR}"
APP_ID = "GiovanniCiccarese.RouteRewind"   # usato da Windows per l'icona nella barra

# Chiave gratuita per le mappe CARTO (https://carto.com/basemaps/apikey).
# Se vuota, l'utente può inserirla dall'app (Impostazioni > Chiave mappe online).
CARTO_KEY = "cb1_5d07_1_527a7250eb713b0508ce1536"

WINDOW_TITLE = f"{APP_NAME} — di {AUTHOR}"


def resource_path(*parts: str) -> str:
    """Percorso di una risorsa, valido sia da sorgente sia nell'exe PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
