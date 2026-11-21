"""Pré-calcul des itinéraires réels (à lancer une seule fois, avec Internet).

Pour chacun des 12 itinéraires de routes.py :
  1. OSRM   : tracé réel sur les routes et vitesse moyenne de chaque tronçon ;
  2. Overpass : stations-service à moins de 300 m du tracé.
Résultat : generator/data/routes_osrm.json, lu par la simulation (hors ligne).

Si Overpass est injoignable, des stations « estimées » sont placées tous les
45 km (champ fuel_source = "estimated") ; relancer plus tard avec --fuel-only
pour les remplacer par les vraies stations sans rappeler OSRM.

Lancement (depuis la racine du dépôt) :
  python -m generator.build_routes              # tracés OSRM + stations
  python -m generator.build_routes --fuel-only  # stations seulement
"""

import argparse

import json
import os
import time
from datetime import datetime, timezone

from .config import ROUTES_FILE
from .geo import distance_km
from .providers.poi import get_pois_near_route
from .providers.routing import get_route
from .routes import CITIES, ROUTES

FUEL_RADIUS_M = 300
# Vitesse de repli pour un tronçon de durée nulle (rond-point, demi-tour)
DEFAULT_SPEED_KMH = 30.0
# Espacement des stations estimées quand Overpass ne répond pas
ESTIMATED_SPACING_KM = 45.0


def osrm_polyline(origin, destination):
    """Points (lon, lat) et vitesse OSRM de chaque segment, à partir des tronçons."""
    lon1, lat1 = CITIES[origin]
    lon2, lat2 = CITIES[destination]
    route = get_route((lat1, lon1), (lat2, lon2))   # get_route attend (lat, lon)

    points, speeds = [], []
    for leg in route["steps"]:
        for step in leg["steps"]:
            coords = step["geometry"]["coordinates"]
            speed = (step["distance"] / step["duration"] * 3.6
                     if step["duration"] > 0 else DEFAULT_SPEED_KMH)
            for lon, lat in coords:
                p = (round(lon, 5), round(lat, 5))
                if points and p == points[-1]:
                    continue                         # point partagé entre deux tronçons
                if points:
                    speeds.append(round(speed, 1))
                points.append(p)
    return points, speeds, route["distance_m"], route["duration_s"]


def project_km(points, poi):
    """Position (km depuis l'origine) du sommet du tracé le plus proche d'un POI."""
    cum = [0.0]
    for a, b in zip(points, points[1:]):
        cum.append(cum[-1] + distance_km(a, b))
    target = (poi["longitude"], poi["latitude"])
    i = min(range(len(points)), key=lambda k: distance_km(points[k], target))
    return round(cum[i], 3)


def route_length_km(points):
    return sum(distance_km(a, b) for a, b in zip(points, points[1:]))


def fuel_stops(points, state):
    """(positions en km, source) : stations réelles via Overpass, sinon estimées.

    state["overpass_ok"] passe à False au premier échec, pour ne pas attendre
    les délais d'expiration sur chacun des 12 itinéraires.
    """
    if state["overpass_ok"]:
        try:
            pois = get_pois_near_route([list(p) for p in points], radius=FUEL_RADIUS_M)
            km = sorted({project_km(points, p) for p in pois if p["category"] == "fuel"})
            return km, "overpass"
        except RuntimeError as exc:
            print(f"  Overpass injoignable ({str(exc)[:120]}...) : stations estimées")
            state["overpass_ok"] = False
    length = route_length_km(points)
    n = int(length // ESTIMATED_SPACING_KM)
    return [round(ESTIMATED_SPACING_KM * (i + 0.5), 1) for i in range(n)], "estimated"


def save(routes_out):
    os.makedirs(os.path.dirname(ROUTES_FILE), exist_ok=True)
    with open(ROUTES_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "OSRM router.project-osrm.org + Overpass API (OpenStreetMap)",
            "routes": routes_out,
        }, f, separators=(",", ":"))
    print(f"\n{len(routes_out)} itinéraires -> {ROUTES_FILE} "
          f"({os.path.getsize(ROUTES_FILE) / 1024:.0f} Ko)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuel-only", action="store_true",
                        help="recalcule seulement les stations du fichier existant")
    args = parser.parse_args()
    state = {"overpass_ok": True}

    if args.fuel_only:
        with open(ROUTES_FILE, encoding="utf-8") as f:
            routes_out = json.load(f)["routes"]
        for r in routes_out:
            r["fuel_stops_km"], r["fuel_source"] = fuel_stops(r["points"], state)
            print(f"{r['route_id']} : {len(r['fuel_stops_km'])} stations ({r['fuel_source']})")
        save(routes_out)
        return

    routes_out = []
    for r in ROUTES:
        rid, origin, destination = r["route_id"], r["origin"], r["destination"]
        try:
            points, speeds, dist_m, dur_s = osrm_polyline(origin, destination)
        except RuntimeError as exc:
            print(f"{rid} {origin} -> {destination} : OSRM indisponible ({exc}), itinéraire ignoré")
            continue

        fuel_km, fuel_source = fuel_stops(points, state)
        routes_out.append({
            "route_id": rid,
            "origin": origin,
            "destination": destination,
            "distance_km": round(dist_m / 1000, 1),
            "duration_min": round(dur_s / 60, 1),
            "points": points,
            "seg_speed_kmh": speeds,
            "fuel_stops_km": fuel_km,
            "fuel_source": fuel_source,
        })
        print(f"{rid} {origin:>9} -> {destination:<9} {dist_m / 1000:6.1f} km  "
              f"{dur_s / 60:5.0f} min  {len(points):5d} points  "
              f"{len(fuel_km):2d} stations ({fuel_source})")
        time.sleep(1)   # politesse envers les serveurs publics OSRM / Overpass

    if not routes_out:
        raise SystemExit("Aucun itinéraire calculé : vérifier la connexion Internet.")
    save(routes_out)


if __name__ == "__main__":
    main()
