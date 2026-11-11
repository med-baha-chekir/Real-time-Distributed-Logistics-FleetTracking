"""Heure de référence des fenêtres temporelles.

Problème : les pipelines « dernière heure » du plan utilisent Date.now().
Si les données ont été générées hier (mode backfill), la fenêtre est vide
pendant la démo ou les mesures. On prend donc comme référence le ts le plus
récent présent dans la collection.

Sans index sur ts, ce calcul parcourt toute la collection (COLLSCAN) ;
avec l'index { ts: -1 } (sprint 3) il ne lit qu'une entrée d'index.
"""

from datetime import datetime, timedelta, timezone


def reference_time(db, collection="telemetry", fallback_now=True):
    """ts le plus récent de la collection (datetime UTC), ou maintenant si vide."""
    doc = db[collection].find_one({}, {"ts": 1, "_id": 0}, sort=[("ts", -1)])
    if doc and doc.get("ts"):
        ts = doc["ts"]
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if fallback_now:
        return datetime.now(timezone.utc)
    return None


def window(db, hours=1.0, collection="telemetry"):
    """(début, fin) de la fenêtre des `hours` dernières heures de données."""
    end = reference_time(db, collection)
    return end - timedelta(hours=hours), end
