"""Météo réelle par région (G11), lue une fois au démarrage via Open-Meteo.

Effet sur la simulation : la pluie réduit la vitesse de 15 %, la température
ambiante décale la température moteur. Sans Internet (ou WEATHER=off), la
simulation continue avec une météo neutre (22 °C, pas de pluie).
"""

from datetime import datetime

from .providers.weather import get_weather
from .routes import CITIES


def load_weather(enabled=True, now=None):
    """{région: {"temperature": °C, "rain": mm}} pour l'heure courante."""
    if not enabled:
        return {}

    now = now or datetime.now()
    hour_prefix = now.strftime("%Y-%m-%dT%H")
    weather = {}
    for region, (lon, lat) in CITIES.items():
        try:
            w = get_weather(lat, lon)
        except (RuntimeError, ValueError, KeyError):
            continue
        # Les heures renvoyées sont en heure locale ("timezone": "auto")
        idx = next((i for i, t in enumerate(w["time"]) if t.startswith(hour_prefix)), 0)
        weather[region] = {
            "temperature": float(w["temperature"][idx]),
            "rain": float(w["rain"][idx] or 0.0),
        }
    return weather
