"""Itinéraires utilisés par la simulation.

Source principale : generator/data/routes_osrm.json, produit une seule fois par
build_routes.py à partir de l'API OSRM (tracé réel sur les routes) et d'Overpass
(stations-service). La simulation n'appelle donc aucune API : elle fonctionne
hors ligne et donne le même résultat à chaque lancement.

Repli : si le fichier est absent, les itinéraires simplifiés de routes.py
(lignes droites, vitesse de référence 80 km/h).
"""

import bisect
import json
import os

from .geo import distance_km, nearest_city
from .routes import ROUTES


class Route:
    """Polyligne parcourable par distance (km depuis l'origine)."""

    def __init__(self, route_id, origin, destination, points, seg_speed_kmh,
                 fuel_stops=None, source="osrm"):
        if len(points) < 2:
            raise ValueError(f"{route_id} : au moins 2 points")
        if len(seg_speed_kmh) != len(points) - 1:
            raise ValueError(f"{route_id} : une vitesse par segment attendue")

        self.route_id = route_id
        self.origin = origin
        self.destination = destination
        self.points = [tuple(p) for p in points]          # [(lon, lat), ...]
        self.seg_speed = list(seg_speed_kmh)               # vitesse de référence par segment
        self.source = source

        # Distance cumulée à chaque sommet
        self.cum_km = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cum_km.append(self.cum_km[-1] + distance_km(a, b))
        self.length_km = self.cum_km[-1]

        # Région de chaque segment (calculée une fois, au milieu du segment)
        self.seg_region = [
            nearest_city(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
            for a, b in zip(self.points, self.points[1:])
        ]

        # Stations-service : position en km le long de la route, triées
        self.fuel_stops_km = sorted(fuel_stops or [])

    def segment_at(self, km):
        """Indice du segment qui contient la distance km."""
        km = min(max(km, 0.0), self.length_km)
        i = bisect.bisect_right(self.cum_km, km) - 1
        return min(max(i, 0), len(self.points) - 2)

    def position_at(self, km):
        """(lon, lat) à la distance km depuis l'origine (interpolation linéaire)."""
        i = self.segment_at(km)
        a, b = self.points[i], self.points[i + 1]
        seg_len = self.cum_km[i + 1] - self.cum_km[i]
        t = 0.0 if seg_len == 0 else (km - self.cum_km[i]) / seg_len
        t = min(max(t, 0.0), 1.0)
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def speed_at(self, km):
        return self.seg_speed[self.segment_at(km)]

    def region_at(self, km):
        return self.seg_region[self.segment_at(km)]

    def next_fuel_stop(self, km, direction):
        """Prochaine station dans le sens de marche (+1 aller, -1 retour), ou None."""
        stops = self.fuel_stops_km
        if not stops:
            return None
        if direction > 0:
            i = bisect.bisect_right(stops, km)
            return stops[i] if i < len(stops) else None
        i = bisect.bisect_left(stops, km) - 1
        return stops[i] if i >= 0 else None


def load_routes(path=None):
    """Charge les itinéraires OSRM, ou les itinéraires simplifiés en repli."""
    from .config import ROUTES_FILE

    path = path or ROUTES_FILE
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [
            Route(r["route_id"], r["origin"], r["destination"], r["points"],
                  r["seg_speed_kmh"], r.get("fuel_stops_km"), source="osrm")
            for r in data["routes"]
        ]

    return [
        Route(r["route_id"], r["origin"], r["destination"], r["waypoints"],
              [80.0] * (len(r["waypoints"]) - 1), source="simplified")
        for r in ROUTES
    ]
