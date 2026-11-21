"""Camion simulé (générateur v2).

Comportement :
  - suit un itinéraire réel (route_network.Route), dans un sens puis dans l'autre ;
  - vitesse cible = vitesse OSRM du tronçon, plafonnée pour un camion, réduite par
    la pluie ; accélération / freinage progressifs + bruit gaussien ;
  - arrêts : feux en ville, livraison à chaque extrémité, ravitaillement ;
  - consommation fonction de la vitesse et de la charge ; réservoir de 400 L ;
  - température moteur qui suit la charge, refroidit à l'arrêt ;
  - anomalies : ~1 % des camions sujets à des surchauffes (> 105 °C),
    ~1 % avec une surconsommation (fuite).

Chaque camion a son propre générateur aléatoire dérivé de la graine globale :
le même SEED donne exactement les mêmes trajectoires, quel que soit le nombre
de processus.
"""

import random
from datetime import datetime, timezone

from . import config as cfg

TRUCK_MODELS = [
    ("Volvo FH 500", 26),
    ("Scania R 450", 24),
    ("Mercedes Actros 1845", 25),
    ("MAN TGX 18.510", 26),
    ("Renault T 480", 24),
    ("Iveco S-Way 490", 22),
]


class Vehicle:
    """Un camion : état courant + avance d'un pas de temps."""

    def __init__(self, vehicle_number, routes, seed=cfg.SEED, weather=None):
        self.number = vehicle_number
        self.vehicle_id = f"VH-{vehicle_number:06d}"
        self.rng = random.Random(seed * 1_000_003 + vehicle_number)
        rng = self.rng

        # Itinéraire, sens et position de départ aléatoires (camions répartis)
        self.route = rng.choice(routes)
        self.direction = rng.choice((1, -1))
        self.km = rng.uniform(0, self.route.length_km)

        # Caractéristiques fixes
        self.model, self.capacity_t = rng.choice(TRUCK_MODELS)
        self.load_factor = rng.uniform(0.4, 1.0)          # charge transportée
        self.home_region = self.route.origin
        self.overheat_prone = rng.random() < cfg.OVERHEAT_PRONE_RATIO
        self.fuel_leak = rng.random() < cfg.FUEL_LEAK_RATIO
        self.driver_factor = rng.uniform(0.92, 1.03)       # conduite prudente ou rapide

        # Météo par région : {région: {"temperature": °C, "rain": mm}}
        self.weather = weather or {}

        # État dynamique
        self.speed_kmh = 0.0
        self.engine_temp_c = rng.uniform(70, 88)
        self.fuel_level_pct = rng.uniform(30, 100)
        self.odometer_km = rng.uniform(10_000, 300_000)
        self.stop_remaining_s = rng.choice((0, 0, 0, rng.uniform(10, 120)))
        self.refuel_at_km = None          # station visée quand le réservoir est bas
        self.overheat_remaining_s = 0.0   # durée restante d'un épisode de surchauffe
        self.trip_seq = 0
        self.trip_id = None
        self._new_trip(datetime.now(timezone.utc))

    # ------------------------------------------------------------------ helpers
    def _new_trip(self, ts):
        self.trip_seq += 1
        self.trip_id = f"TR-{ts:%Y%m%d}-{self.number:06d}-{self.trip_seq:03d}"
        # Point de livraison de ce trajet : entre 0,2 et 3 km avant la fin de l'itinéraire
        self.delivery_margin_km = self.rng.uniform(0.2, min(3.0, self.route.length_km / 4))

    def _ambient(self, region):
        return self.weather.get(region, {}).get("temperature", 22.0)

    def _rain(self, region):
        return self.weather.get(region, {}).get("rain", 0.0)

    def reference_doc(self, ts):
        """Fiche du camion pour la collection vehicles."""
        return {
            "_id": self.vehicle_id,
            "model": self.model,
            "capacity_t": self.capacity_t,
            "home_region": self.home_region,
            "status": "active",
            "created_at": ts,
        }

    # --------------------------------------------------------------------- step
    def step(self, dt, ts):
        """Avance de dt secondes et renvoie le document telemetry daté ts."""
        rng = self.rng
        route = self.route
        region = route.region_at(self.km)
        ambient = self._ambient(region)

        if self.stop_remaining_s > 0:
            # ---- À l'arrêt : vitesse nulle, moteur au ralenti
            self.stop_remaining_s -= dt
            self.speed_kmh = max(0.0, self.speed_kmh - cfg.BRAKE_KMH_PER_S * dt)
            if self.stop_remaining_s <= 0:
                self.stop_remaining_s = 0.0
        else:
            # ---- En marche : vitesse cible du tronçon
            ref = route.speed_at(self.km)
            target = min(ref * self.driver_factor, cfg.TRUCK_MAX_SPEED)
            target *= 1.05 - 0.1 * self.load_factor          # camion chargé = plus lent
            if self._rain(region) > 0.5:
                target *= 0.85                                # pluie : on ralentit
            delta = target - self.speed_kmh
            max_up, max_down = cfg.ACCEL_KMH_PER_S * dt, cfg.BRAKE_KMH_PER_S * dt
            self.speed_kmh += max(-max_down, min(max_up, delta))
            self.speed_kmh = max(0.0, self.speed_kmh + rng.gauss(0, cfg.SPEED_NOISE))
            self.speed_kmh = min(self.speed_kmh, cfg.TRUCK_MAX_SPEED + 8)

            # Feu rouge / bouchon en zone urbaine (tronçon lent)
            if ref < 55 and rng.random() < 0.015 * dt / 5:
                self.stop_remaining_s = rng.uniform(20, 90)

            self._advance(self.speed_kmh * dt / 3600, ts)

        self._update_fuel(dt)
        self._update_engine(dt, ambient)

        lon, lat = route.position_at(self.km)
        return {
            "vehicle_id": self.vehicle_id,
            "ts": ts,
            "location": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "region": route.region_at(self.km),
            "speed_kmh": round(self.speed_kmh, 1),
            "fuel_level_pct": round(self.fuel_level_pct, 1),
            "fuel_rate_lph": round(self.fuel_rate_lph, 1),
            "engine_temp_c": round(self.engine_temp_c, 1),
            "odometer_km": round(self.odometer_km, 1),
            "trip_id": self.trip_id,
            "route_id": route.route_id,
        }

    def _advance(self, dist_km, ts):
        """Avance le long de la route ; gère arrivée, livraison et ravitaillement."""
        route = self.route
        self.odometer_km += dist_km
        new_km = self.km + self.direction * dist_km

        # Station-service visée atteinte : arrêt et plein
        if self.refuel_at_km is not None and (
                (self.direction > 0 and new_km >= self.refuel_at_km)
                or (self.direction < 0 and new_km <= self.refuel_at_km)):
            new_km = self.refuel_at_km
            self._refuel()

        # Arrivée en ville : livraison (5 à 20 min) puis demi-tour. Le point de
        # livraison est tiré dans les derniers km de l'itinéraire (marge propre à
        # chaque trajet), sinon tous les camions s'empileraient sur le même point.
        lo, hi = self.delivery_margin_km, route.length_km - self.delivery_margin_km
        if (self.direction > 0 and new_km >= hi) or (self.direction < 0 and new_km <= lo):
            new_km = hi if self.direction > 0 else lo
            self.direction = -self.direction
            self.stop_remaining_s = self.rng.uniform(300, 1200)
            self.refuel_at_km = None
            self._new_trip(ts)

        self.km = new_km

    def _refuel(self):
        self.stop_remaining_s = self.rng.uniform(300, 900)
        self.fuel_level_pct = self.rng.uniform(92, 100)
        self.refuel_at_km = None

    def _update_fuel(self, dt):
        v = self.speed_kmh
        if v < 1:
            rate = 2.5                                         # ralenti
        else:
            rate = (10 + 0.18 * v + 0.0022 * v * v) * (0.75 + 0.45 * self.load_factor)
        if self.fuel_leak:
            rate *= 1.6                                        # anomalie : surconsommation
        self.fuel_rate_lph = max(0.0, rate + self.rng.gauss(0, 0.8))
        self.fuel_level_pct -= self.fuel_rate_lph * dt / 3600 / cfg.TANK_LITERS * 100
        self.fuel_level_pct = max(0.0, self.fuel_level_pct)

        # Réservoir bas : viser la prochaine station, sinon s'arrêter sur place
        if self.fuel_level_pct < cfg.REFUEL_THRESHOLD_PCT and self.refuel_at_km is None \
                and self.stop_remaining_s == 0:
            stop = self.route.next_fuel_stop(self.km, self.direction)
            if stop is not None and abs(stop - self.km) < 60:
                self.refuel_at_km = stop
            else:
                self._refuel()

    def _update_engine(self, dt, ambient):
        rng = self.rng
        if self.speed_kmh < 1:
            target = ambient + 45                              # moteur qui refroidit
        else:
            target = 78 + 0.10 * self.speed_kmh + 6 * self.load_factor + 0.15 * (ambient - 20)

        # Épisodes de surchauffe des camions fragiles
        if self.overheat_prone:
            if self.overheat_remaining_s > 0:
                self.overheat_remaining_s -= dt
                target += 30
            elif rng.random() < 0.012 * dt / 5:
                self.overheat_remaining_s = rng.uniform(120, 600)

        # Le moteur rejoint la cible progressivement (constante de temps ~ 2 min)
        alpha = min(1.0, dt / 120)
        self.engine_temp_c += (target - self.engine_temp_c) * alpha + rng.gauss(0, 0.4)
