
import math
import random
from datetime import datetime, timezone

from config import MIN_SPEED, MAX_SPEED, SPEED_NOISE
from routes import ROUTES


def distance_km(a, b):
    """Calcule la distance approximative entre deux points GPS."""

    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)

    dlon = lon2 - lon1
    dlat = lat2 - lat1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 6371 * 2 * math.asin(math.sqrt(h))


class Vehicle:
    """Représente un camion simulé."""

    def __init__(self, vehicle_number):
        # Identifiant unique du camion
        self.vehicle_id = f"VH-{vehicle_number:06d}"

        # Affectation aléatoire d'un itinéraire
        self.route = random.choice(ROUTES)
        self.waypoints = self.route["waypoints"]

        # Index du segment parcouru entre deux waypoints
        self.segment_index = 0

        # Fraction du segment déjà parcourue : entre 0 et 1
        self.segment_progress = 0.0

        # Vitesse initiale aléatoire
        self.speed_kmh = random.uniform(MIN_SPEED, MAX_SPEED)

        # Mesures initiales
        self.engine_temp_c = 85.0
        self.fuel_level_pct = random.uniform(40, 100)
        self.odometer_km = random.uniform(10_000, 300_000)

        # Identifiant du trajet
        self.trip_id = f"TR-{random.randint(0, 999999):06d}"

    def step(self, dt_seconds):
        """
        Fait avancer le camion pendant dt_seconds secondes
        et retourne un document de télémétrie.
        """

        # Variation de vitesse suivant une loi normale
        self.speed_kmh += random.gauss(0, SPEED_NOISE)

        # Limitation de la vitesse aux bornes configurées
        self.speed_kmh = max(
            MIN_SPEED,
            min(MAX_SPEED, self.speed_kmh)
        )

        # Distance parcourue durant ce pas de temps
        remaining_km = self.speed_kmh * dt_seconds / 3600

        # Avance le long des segments, même si un waypoint
        # est dépassé pendant le pas de temps.
        while remaining_km > 0:
            start = self.waypoints[self.segment_index]
            end = self.waypoints[self.segment_index + 1]

            segment_length = distance_km(start, end)

            # Évite une division par zéro si deux waypoints
            # sont identiques.
            if segment_length == 0:
                self.segment_index += 1
                self.segment_progress = 0.0

            else:
                segment_remaining = (
                    segment_length * (1 - self.segment_progress)
                )

                if remaining_km >= segment_remaining:
                    remaining_km -= segment_remaining
                    self.segment_index += 1
                    self.segment_progress = 0.0

                else:
                    self.segment_progress += (
                        remaining_km / segment_length
                    )
                    remaining_km = 0.0

            # Arrivée : le camion reprend le même itinéraire
            # dans le sens inverse.
            if self.segment_index >= len(self.waypoints) - 1:
                self.waypoints = list(reversed(self.waypoints))
                self.segment_index = 0
                self.segment_progress = 0.0

        # Interpolation linéaire sur le segment courant
        start = self.waypoints[self.segment_index]
        end = self.waypoints[self.segment_index + 1]
        p = self.segment_progress

        lon = start[0] + (end[0] - start[0]) * p
        lat = start[1] + (end[1] - start[1]) * p

        # Bruit gaussien sur la température moteur
        self.engine_temp_c += (
            (90 - self.engine_temp_c) * 0.1
            + random.gauss(0, 1)
        )

        # Distance totale ajoutée au compteur kilométrique
        self.odometer_km += self.speed_kmh * dt_seconds / 3600

        # Consommation simplifiée de carburant
        fuel_rate_lph = max(
            5.0,
            15 + 0.25 * self.speed_kmh + random.gauss(0, 2)
        )

        self.fuel_level_pct = max(
            0.0,
            self.fuel_level_pct
            - fuel_rate_lph * dt_seconds / 3600 / 6
        )

        # Construction du document MongoDB
        return {
            "vehicle_id": self.vehicle_id,
            "ts": datetime.now(timezone.utc),
            "trip_id": self.trip_id,
            "route_id": self.route["route_id"],
            "location": {
                "type": "Point",
                "coordinates": [round(lon, 6), round(lat, 6)]
            },
            "speed_kmh": round(self.speed_kmh, 1),
            "engine_temp_c": round(self.engine_temp_c, 1),
            "fuel_level_pct": round(self.fuel_level_pct, 1),
            "fuel_rate_lph": round(fuel_rate_lph, 1),
            "odometer_km": round(self.odometer_km, 1),
        }
