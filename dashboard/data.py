"""Couche données du dashboard : requêtes MongoDB → DataFrames (sans Streamlit).

Toutes les requêtes viennent de queries/pipelines.py (mesurées au sprint 3).
Lecture en readPreference "primaryPreferred" : si le primaire tombe, les lectures
passent immédiatement sur un secondaire pendant l'élection (le dashboard continue
d'afficher des données ; seules les écritures attendent le nouveau primaire).
"""

import os
from datetime import timedelta

import json

import pandas as pd
from pymongo import MongoClient, ReadPreference

from queries.pipelines import (
    a_avg_speed_by_region,
    d_overheat_alerts,
    e_speed_distribution,
    geo_near_point,
)
from queries.ref_time import reference_time

MONGO_URI = os.getenv(
    "MONGO_URI", "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0"
)
DB_NAME = os.getenv("DB_NAME", "fleet")

OVERHEAT_C = 105.0          # seuil d'alerte (pipeline d)
STOPPED_KMH = 1.0           # en dessous : camion à l'arrêt
ACTIVE_MINUTES = 5          # un camion sans message depuis 5 min n'est plus « actif »
STALE_SECONDS = 60          # au-delà : données figées (aucun générateur ne tourne)


def format_age(seconds):
    """Durée lisible : 45 s, 12 min, 2 h 05, 3 j."""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    if s < 86400:
        return f"{s // 3600} h {s % 3600 // 60:02d}"
    return f"{s // 86400} j"

# Couleurs [R, G, B, A] des points de la carte
STATUS_COLORS = {
    "alerte": [220, 38, 38, 230],
    "arrêt": [120, 120, 120, 200],
    "en route": [22, 163, 74, 210],
}
SPEED_LABELS = {0: "0–20", 20: "20–40", 40: "40–60", 60: "60–80", 80: "80–100",
                100: "100–130", "hors plage": "hors plage"}


def make_client(uri=MONGO_URI):
    """Client court en délais : une panne doit être signalée vite, pas bloquer la page."""
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=3000,
        connectTimeoutMS=3000,
        socketTimeoutMS=15000,
        readPreference="primaryPreferred",
        appname="fleet-dashboard",
    )


ROUTES_FILE = os.getenv(
    "ROUTES_FILE",
    os.path.join(os.path.dirname(__file__), "..", "generator", "data", "routes_osrm.json"),
)


def load_route_paths(path=ROUTES_FILE):
    """Tracés des itinéraires (fond de carte) ; liste vide si le fichier est absent."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        routes = json.load(f)["routes"]
    return [{"route": f"{r['route_id']} {r['origin']} → {r['destination']}",
             "path": [[lon, lat] for lon, lat in r["points"][::5]]} for r in routes]


# ------------------------------------------------------------------ transformations pures
def classify(speed_kmh, engine_temp_c):
    """Statut d'un camion pour la carte et les indicateurs."""
    if engine_temp_c is not None and engine_temp_c > OVERHEAT_C:
        return "alerte"
    if speed_kmh is None or speed_kmh < STOPPED_KMH:
        return "arrêt"
    return "en route"


def state_frame(docs):
    """Documents vehicle_state → DataFrame avec lon, lat, statut et couleur."""
    rows = []
    for d in docs:
        lon, lat = d["location"]["coordinates"]
        speed, temp = d.get("speed_kmh"), d.get("engine_temp_c")
        status = classify(speed, temp)
        rows.append({
            "vehicle_id": d["_id"], "lon": lon, "lat": lat,
            "region": d.get("region"), "route_id": d.get("route_id"),
            "speed_kmh": speed, "engine_temp_c": temp,
            "fuel_level_pct": d.get("fuel_level_pct"), "last_ts": d.get("last_ts"),
            "status": status, "color": STATUS_COLORS[status],
        })
    cols = ["vehicle_id", "lon", "lat", "region", "route_id", "speed_kmh", "engine_temp_c",
            "fuel_level_pct", "last_ts", "status", "color"]
    return pd.DataFrame(rows, columns=cols)


def kpis(state, ref, avg_fuel_lph, alerts_24h):
    """Indicateurs clés à partir de vehicle_state (déjà en mémoire)."""
    if state.empty:
        return {"trucks": 0, "active": 0, "moving": 0, "avg_speed": None,
                "avg_fuel_lph": avg_fuel_lph, "overheating_now": 0, "alerts_24h": alerts_24h}
    last = pd.to_datetime(state["last_ts"], utc=True)
    active = state[last >= pd.Timestamp(ref) - pd.Timedelta(minutes=ACTIVE_MINUTES)]
    moving = active[active["speed_kmh"] >= STOPPED_KMH]
    return {
        "trucks": int(len(state)),
        "active": int(len(active)),
        "moving": int(len(moving)),
        "avg_speed": round(float(moving["speed_kmh"].mean()), 1) if len(moving) else None,
        "avg_fuel_lph": avg_fuel_lph,
        "overheating_now": int((state["status"] == "alerte").sum()),
        "alerts_24h": alerts_24h,
    }


def histogram_frame(rows):
    """Résultat du $bucket (pipeline e) → DataFrame ordonné avec libellés lisibles."""
    order = list(SPEED_LABELS)
    data = [{"tranche": SPEED_LABELS.get(r["_id"], str(r["_id"])), "messages": r["count"],
             "_o": order.index(r["_id"]) if r["_id"] in order else 99} for r in rows]
    df = pd.DataFrame(data, columns=["tranche", "messages", "_o"]).sort_values("_o")
    return df.drop(columns="_o").reset_index(drop=True)


# ------------------------------------------------------------------ requêtes
def fetch_reference_time(db):
    return reference_time(db)


def fetch_state(db):
    """D1 : dernière position de chaque camion (2 000 documents, quelques ms)."""
    return state_frame(db.vehicle_state.find({}, {"_id": 1, "location": 1, "region": 1,
                                                  "route_id": 1, "speed_kmh": 1,
                                                  "engine_temp_c": 1, "fuel_level_pct": 1,
                                                  "last_ts": 1}))


def fetch_avg_fuel(db, ref, minutes=5):
    """D2 : consommation moyenne de la flotte sur les dernières minutes (index ts / couvrant)."""
    res = list(db.telemetry.aggregate([
        {"$match": {"ts": {"$gte": ref - timedelta(minutes=minutes), "$lte": ref}}},
        {"$group": {"_id": None, "avg": {"$avg": "$fuel_rate_lph"}}},
    ]))
    return round(res[0]["avg"], 1) if res else None


def fetch_speed_by_region(db, ref, hours=1):
    """D3 : pipeline a."""
    coll, pipeline = a_avg_speed_by_region(ref, hours=hours)
    rows = list(db[coll].aggregate(pipeline))
    df = pd.DataFrame([{"région": r["_id"], "vitesse moyenne (km/h)": round(r["avg_speed"], 1),
                        "messages": r["messages"]} for r in rows],
                      columns=["région", "vitesse moyenne (km/h)", "messages"])
    return df


def fetch_speed_histogram(db, ref, hours=1):
    """D4 : pipeline e."""
    coll, pipeline = e_speed_distribution(ref, hours=hours)
    return histogram_frame(list(db[coll].aggregate(pipeline)))


def fetch_alerts(db, ref, hours=24):
    """D5 : pipeline d, complété par la région et la position actuelles du camion."""
    coll, pipeline = d_overheat_alerts(ref, hours=hours)
    rows = list(db[coll].aggregate(pipeline))
    where = {d["_id"]: d for d in db.vehicle_state.find(
        {"_id": {"$in": [r["_id"] for r in rows]}},
        {"region": 1, "engine_temp_c": 1, "speed_kmh": 1})}
    return pd.DataFrame([{
        "camion": r["_id"],
        "messages > 105 °C": r["count"],
        "max (°C)": round(r["max_temp"], 1),
        "région actuelle": where.get(r["_id"], {}).get("region"),
        "température actuelle (°C)": where.get(r["_id"], {}).get("engine_temp_c"),
    } for r in rows], columns=["camion", "messages > 105 °C", "max (°C)", "région actuelle",
                               "température actuelle (°C)"])


def fetch_nearby(db, lon, lat, radius_km):
    """D6 : camions dans un rayon (requête 12.1, $geoNear sur l'index 2dsphere)."""
    coll, pipeline = geo_near_point(point=[lon, lat], max_km=radius_km)
    docs = list(db[coll].aggregate(pipeline))
    df = state_frame(docs)
    df["distance_km"] = [round(d["distance_m"] / 1000, 2) for d in docs]
    return df


def fetch_cluster_status(client):
    """D7 : état des nœuds du Replica Set (PRIMARY / SECONDARY / injoignable)."""
    # primaryPreferred : la commande répond aussi pendant une élection (aucun primaire)
    st = client.admin.command("replSetGetStatus",
                              read_preference=ReadPreference.PRIMARY_PREFERRED)
    return [{"nœud": m["name"].split(":")[0], "état": m["stateStr"], "santé": m["health"]}
            for m in st["members"]]
