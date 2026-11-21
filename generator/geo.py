"""Fonctions géographiques. Toutes les coordonnées sont en (longitude, latitude)."""

import math

from .routes import CITIES

EARTH_RADIUS_KM = 6371.0


def distance_km(a, b):
    """Distance de Haversine entre deux points (lon, lat), en km."""
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def nearest_city(point):
    """Région d'un point = ville de CITIES la plus proche (docs/data-model.md)."""
    return min(CITIES, key=lambda name: distance_km(point, CITIES[name]))
