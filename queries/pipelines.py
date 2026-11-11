"""Agrégations (a à e) et requêtes géospatiales du plan, en Python.

Chaque fonction renvoie (collection, pipeline). Les fenêtres temporelles
dépendent d'une heure de référence (voir ref_time.py) et non de « maintenant ».

Corrections par rapport au plan : b, e et geo_zone_avg_speed ont une
fenêtre temporelle ($match sur ts), sinon $group parcourt toute la collection.

Base commune pour explain_baseline.py (mesures) et le dashboard (sprint 4).
"""

from datetime import timedelta

TUNIS = [10.1815, 36.8065]  # [lon, lat]
TUNIS_ZONE = {
    "type": "Polygon",
    "coordinates": [[[10.10, 36.78], [10.25, 36.78], [10.25, 36.87],
                     [10.10, 36.87], [10.10, 36.78]]],
}


def a_avg_speed_by_region(ref, hours=1):
    """a) Vitesse moyenne par région sur la dernière heure."""
    return "telemetry", [
        {"$match": {"ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref}}},
        {"$group": {"_id": "$region", "avg_speed": {"$avg": "$speed_kmh"},
                    "messages": {"$sum": 1}}},
        {"$sort": {"avg_speed": -1}},
    ]


def b_avg_fuel_by_vehicle(ref, hours=1, limit=20):
    """b) Consommation moyenne par camion (top 20) sur la dernière heure."""
    return "telemetry", [
        {"$match": {"ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref}}},
        {"$group": {"_id": "$vehicle_id", "avg_fuel_rate": {"$avg": "$fuel_rate_lph"}}},
        {"$sort": {"avg_fuel_rate": -1}},
        {"$limit": limit},
    ]


def c_vehicles_by_region(ref=None):
    """c) Nombre de véhicules par région (position actuelle)."""
    return "vehicle_state", [
        {"$group": {"_id": "$region", "vehicles": {"$sum": 1}}},
        {"$sort": {"vehicles": -1}},
    ]


def d_overheat_alerts(ref, hours=24, threshold=105):
    """d) Alertes de surchauffe sur les dernières 24 h."""
    return "telemetry", [
        {"$match": {"engine_temp_c": {"$gt": threshold},
                    "ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref}}},
        {"$group": {"_id": "$vehicle_id", "max_temp": {"$max": "$engine_temp_c"},
                    "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]


def e_speed_distribution(ref, hours=1):
    """e) Distribution des vitesses sur la dernière heure."""
    return "telemetry", [
        {"$match": {"ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref}}},
        {"$bucket": {"groupBy": "$speed_kmh",
                     "boundaries": [0, 20, 40, 60, 80, 100, 130],
                     "default": "hors plage",
                     "output": {"count": {"$sum": 1}}}},
    ]


def f_vehicle_history(ref, vehicle_id="VH-000001", hours=24):
    """Historique d'un camion (index { vehicle_id: 1, ts: -1 })."""
    return "telemetry", [
        {"$match": {"vehicle_id": vehicle_id,
                    "ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref}}},
        {"$sort": {"ts": -1}},
        {"$limit": 100},
    ]


def geo_near_point(ref=None, point=TUNIS, max_km=10):
    """12.1) Camions à moins de 10 km d'un point (exige l'index 2dsphere)."""
    return "vehicle_state", [
        {"$geoNear": {"near": {"type": "Point", "coordinates": point},
                      "distanceField": "distance_m", "maxDistance": max_km * 1000,
                      "spherical": True}},
    ]


def geo_in_zone(ref=None, zone=TUNIS_ZONE):
    """12.2) Camions dans un polygone (zone de livraison)."""
    return "vehicle_state", [
        {"$match": {"location": {"$geoWithin": {"$geometry": zone}}}},
    ]


def geo_zone_avg_speed(ref, zone=TUNIS_ZONE, hours=1):
    """12.3) Vitesse moyenne dans une zone (avec fenêtre temporelle)."""
    return "telemetry", [
        {"$match": {"ts": {"$gte": ref - timedelta(hours=hours), "$lte": ref},
                    "location": {"$geoWithin": {"$geometry": zone}}}},
        {"$group": {"_id": None, "avg_speed": {"$avg": "$speed_kmh"},
                    "messages": {"$sum": 1}}},
    ]


ALL = {
    "a_avg_speed_by_region": a_avg_speed_by_region,
    "b_avg_fuel_by_vehicle": b_avg_fuel_by_vehicle,
    "c_vehicles_by_region": c_vehicles_by_region,
    "d_overheat_alerts": d_overheat_alerts,
    "e_speed_distribution": e_speed_distribution,
    "f_vehicle_history": f_vehicle_history,
    "geo_near_point": geo_near_point,
    "geo_in_zone": geo_in_zone,
    "geo_zone_avg_speed": geo_zone_avg_speed,
}
