import math
import pandas as pd
import folium
import matplotlib.pyplot as plt

from generator.vehicle import Vehicle
from generator.config import MIN_SPEED, MAX_SPEED

# 10 camions × 300 mesures = 3 000 points
TRUCK_COUNT = 10
POINTS_PER_TRUCK = 300
INTERVAL_SECONDS = 5

vehicles = [Vehicle(i) for i in range(1, TRUCK_COUNT + 1)]
records = []
tracks = {}

for vehicle in vehicles:
    vehicle_id = vehicle.vehicle_id if hasattr(vehicle, "vehicle_id") else None
    track = []

    for _ in range(POINTS_PER_TRUCK):
        doc = vehicle.step(INTERVAL_SECONDS)

        # GeoJSON : [longitude, latitude]
        lon, lat = doc["location"]["coordinates"]

        if vehicle_id is None:
            vehicle_id = doc.get("vehicle_id", "Camion")

        point = {
            "vehicle_id": doc.get("vehicle_id", vehicle_id),
            "longitude": lon,
            "latitude": lat,
            "speed_kmh": doc["speed_kmh"],
            "ts": doc["ts"],
        }

        records.append(point)
        track.append([lat, lon])  # Folium attend [latitude, longitude]

    tracks[vehicle_id] = track

df = pd.DataFrame(records)
df.to_csv("trajectory_points.csv", index=False)

# Carte centrée sur la Tunisie
m = folium.Map(location=[34.0, 9.5], zoom_start=6)

for vehicle_id, track in tracks.items():
    if not track:
        continue

    folium.PolyLine(
        track,
        tooltip=str(vehicle_id),
        weight=3,
        opacity=0.8,
    ).add_to(m)

    folium.CircleMarker(
        track[0],
        radius=4,
        tooltip=f"{vehicle_id} - départ",
        color="green",
        fill=True,
    ).add_to(m)

    folium.CircleMarker(
        track[-1],
        radius=4,
        tooltip=f"{vehicle_id} - dernière position",
        color="red",
        fill=True,
    ).add_to(m)

m.save("trajectoires_camions.html")

# Vérifications numériques
numeric_speeds = pd.to_numeric(df["speed_kmh"], errors="coerce")
valid_speeds = numeric_speeds.dropna()

print(f"Nombre total de points : {len(df)}")
print(f"Nombre de camions : {df['vehicle_id'].nunique()}")
print(f"Vitesse minimale observée : {valid_speeds.min():.2f} km/h")
print(f"Vitesse maximale observée : {valid_speeds.max():.2f} km/h")
print(f"Vitesse moyenne observée : {valid_speeds.mean():.2f} km/h")

# Contrôle des coordonnées
assert df["longitude"].between(7, 12).all(), "Longitude hors de la plage attendue"
assert df["latitude"].between(30, 38).all(), "Latitude hors de la plage attendue"
assert numeric_speeds.notna().all(), "Certaines vitesses ne sont pas numériques"
assert math.isfinite(valid_speeds.mean()), "Vitesse moyenne invalide"

# Contrôle des vitesses selon les limites configurées
outside = ~numeric_speeds.between(MIN_SPEED, MAX_SPEED)
print(f"Points avec vitesse hors limites configurées : {outside.sum()}")

# Figure statique pour le rapport
plt.figure(figsize=(10, 7))

for vehicle_id, track in tracks.items():
    latitudes = [p[0] for p in track]
    longitudes = [p[1] for p in track]
    plt.plot(longitudes, latitudes, linewidth=1, label=str(vehicle_id))

plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.title("Trajectoires simulées des camions en Tunisie")
plt.grid(True)
plt.tight_layout()
plt.savefig("trajectoires_rapport.png", dpi=300, bbox_inches="tight")
plt.close()

print("Carte interactive : trajectoires_camions.html")
print("Figure du rapport : trajectoires_rapport.png")
print("Données exportées : trajectory_points.csv")
