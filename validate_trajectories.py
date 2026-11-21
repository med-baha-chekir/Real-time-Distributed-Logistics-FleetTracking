"""Validation visuelle et statistique du générateur v2 (sans MongoDB).

Simule des camions pendant 2 heures, puis :
  - trace les trajectoires sur une carte (trajectoires_camions.html) et une figure
    pour le rapport (trajectoires_rapport.png) ;
  - affiche les statistiques attendues par les pipelines du plan : vitesses
    (histogramme e), régions (a, c), alertes de surchauffe (d), arrêts.

Lancement (depuis la racine du dépôt, dépendances : generator/requirements-dev.txt) :
  python validate_trajectories.py
"""

import math
from datetime import datetime, timedelta, timezone

import folium
import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from generator import config as cfg  # noqa: E402
from generator.route_network import load_routes  # noqa: E402
from generator.vehicle import Vehicle  # noqa: E402

TRUCK_COUNT = 200
STEPS = 1440            # 1440 x 5 s = 2 heures simulées
INTERVAL_SECONDS = 5
TRACKS_ON_MAP = 25

routes = load_routes()
vehicles = [Vehicle(n, routes) for n in range(1, TRUCK_COUNT + 1)]
start = datetime.now(timezone.utc) - timedelta(seconds=STEPS * INTERVAL_SECONDS)

records = []
for k in range(STEPS):
    ts = start + timedelta(seconds=k * INTERVAL_SECONDS)
    for v in vehicles:
        d = v.step(INTERVAL_SECONDS, ts)
        lon, lat = d["location"]["coordinates"]
        records.append({"vehicle_id": d["vehicle_id"], "ts": ts, "longitude": lon,
                        "latitude": lat, "region": d["region"], "route_id": d["route_id"],
                        "speed_kmh": d["speed_kmh"], "engine_temp_c": d["engine_temp_c"],
                        "fuel_rate_lph": d["fuel_rate_lph"]})

df = pd.DataFrame(records)
df.to_csv("trajectory_points.csv", index=False)

# --- Carte interactive ---------------------------------------------------------
m = folium.Map(location=[35.5, 9.8], zoom_start=7)
for r in routes:   # itinéraires en gris
    folium.PolyLine([[lat, lon] for lon, lat in r.points], color="gray",
                    weight=2, opacity=0.5, tooltip=f"{r.route_id} {r.origin}-{r.destination}").add_to(m)
for vid, g in list(df.groupby("vehicle_id"))[:TRACKS_ON_MAP]:
    track = g[["latitude", "longitude"]].values.tolist()
    folium.PolyLine(track, weight=3, opacity=0.9, tooltip=vid).add_to(m)
    folium.CircleMarker(track[-1], radius=4, color="red", fill=True,
                        tooltip=f"{vid} - dernière position").add_to(m)
m.save("trajectoires_camions.html")

# --- Figure pour le rapport ------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(14, 7))
for r in routes:
    xs, ys = zip(*r.points)
    axes[0].plot(xs, ys, color="lightgray", linewidth=1)
for vid, g in list(df.groupby("vehicle_id"))[:TRACKS_ON_MAP]:
    axes[0].plot(g["longitude"], g["latitude"], linewidth=1.2)
axes[0].set(xlabel="Longitude", ylabel="Latitude", title="Trajectoires simulées (routes OSRM)")
axes[0].set_aspect("equal")
axes[1].hist(df["speed_kmh"], bins=[0, 1, 20, 40, 60, 80, 100, 110], edgecolor="black")
axes[1].set(xlabel="Vitesse (km/h)", ylabel="Messages", title="Distribution des vitesses")
plt.tight_layout()
plt.savefig("trajectoires_rapport.png", dpi=200, bbox_inches="tight")
plt.close()

# --- Contrôles ------------------------------------------------------------------
assert df["longitude"].between(7, 12).all(), "Longitude hors Tunisie"
assert df["latitude"].between(30, 38).all(), "Latitude hors Tunisie"
assert math.isfinite(df["speed_kmh"].mean())

buckets = pd.cut(df["speed_kmh"], [-0.1, 1, 20, 40, 60, 80, 100, 130],
                 labels=["arrêt", "1-20", "20-40", "40-60", "60-80", "80-100", "100+"])
alerts = df[df["engine_temp_c"] > cfg.OVERHEAT_THRESHOLD_C]

print(f"Itinéraires : {routes[0].source} | points : {len(df)} | camions : {df['vehicle_id'].nunique()}")
print(f"Vitesse : min {df['speed_kmh'].min():.1f} | moyenne {df['speed_kmh'].mean():.1f} | "
      f"max {df['speed_kmh'].max():.1f} km/h")
print("Distribution des vitesses (%) :")
print((buckets.value_counts(normalize=True).sort_index() * 100).round(1).to_string())
print(f"Régions couvertes : {df['region'].nunique()} / 12")
print((df["region"].value_counts(normalize=True) * 100).round(1).to_string())
print(f"Alertes > {cfg.OVERHEAT_THRESHOLD_C:.0f} °C : {len(alerts)} messages, "
      f"{alerts['vehicle_id'].nunique()} camions")
print(f"Consommation moyenne : {df['fuel_rate_lph'].mean():.1f} L/h")
print("Carte : trajectoires_camions.html | Figure : trajectoires_rapport.png | "
      "Données : trajectory_points.csv")
