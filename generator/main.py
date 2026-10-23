import os, time, math, random
from datetime import datetime, timezone
from pymongo import MongoClient, UpdateOne, WriteConcern
from pymongo.errors import PyMongoError

URI = os.getenv("MONGO_URI")
N = int(os.getenv("TRUCKS", 500))
INTERVAL = float(os.getenv("INTERVAL", 5))   # 0 = as fast as possible
DURATION = int(os.getenv("DURATION", 0))     # seconds, 0 = forever
BATCH = 500
# [longitude, latitude]  <- GeoJSON order!
CITIES = {"Tunis":(10.1815,36.8065),"Sousse":(10.6411,35.8256),"Sfax":(10.7600,34.7406),
          "Bizerte":(9.8739,37.2746),"Gabes":(10.0982,33.8815),"Kairouan":(10.0963,35.6781),
          "Nabeul":(10.7357,36.4561),"Gafsa":(8.7757,34.4250)}

def dist_km(a, b):
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dlon, dlat = math.radians(b[0]-a[0]), la2-la1
    h = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return 6371*2*math.asin(math.sqrt(h))

def region_of(p):
    return min(CITIES, key=lambda c: dist_km(p, CITIES[c]))

class Vehicle:
    def __init__(s, i):
        s.id = f"VH-{i:06d}"
        s.o, s.d = random.sample(list(CITIES), 2)
        s.p = random.random(); s.speed = random.uniform(60, 90)
        s.temp = 85.0; s.fuel = random.uniform(40, 100)
        s.odo = random.uniform(1e4, 3e5); s.trip = f"TR-{random.randint(0,10**6):06d}"
    def step(s, dt=5):
        a, b = CITIES[s.o], CITIES[s.d]; L = dist_km(a, b)
        s.speed = max(0, min(110, s.speed + random.gauss(0, 3)))
        s.p += s.speed*dt/3600/L
        if s.p >= 1: s.o, s.d, s.p = s.d, s.o, 0.0
        a, b = CITIES[s.o], CITIES[s.d]
        pos = [a[0]+(b[0]-a[0])*s.p, a[1]+(b[1]-a[1])*s.p]
        s.temp += (90 - s.temp)*0.1 + random.gauss(0, 1)
        if random.random() < 0.002: s.temp = random.uniform(106, 115)   # anomaly
        rate = 15 + 0.25*s.speed + random.gauss(0, 2)
        s.fuel = s.fuel - rate*dt/3600/6 if s.fuel > 10 else 100.0
        s.odo += s.speed*dt/3600
        return {"vehicle_id": s.id, "ts": datetime.now(timezone.utc),
                "location": {"type": "Point", "coordinates": [round(pos[0],5), round(pos[1],5)]},
                "region": region_of(pos), "speed_kmh": round(s.speed,1),
                "fuel_level_pct": round(s.fuel,1), "fuel_rate_lph": round(rate,1),
                "engine_temp_c": round(s.temp,1), "odometer_km": round(s.odo,1), "trip_id": s.trip}

client = MongoClient(URI)
db = client.fleet
tel = db.get_collection("telemetry", write_concern=WriteConcern("majority"))
state = db.get_collection("vehicle_state", write_concern=WriteConcern("majority"))
vehicles = [Vehicle(i) for i in range(N)]
db.vehicles.delete_many({})
db.vehicles.insert_many([{"_id": v.id, "model": "Volvo FH 500", "capacity_t": 26,
    "home_region": v.o, "status": "active", "created_at": datetime.now(timezone.utc)} for v in vehicles])

sent, t0 = 0, time.time()
while True:
    t = time.time()
    docs = [v.step() for v in vehicles]
    try:
        for i in range(0, len(docs), BATCH):
            chunk = docs[i:i+BATCH]
            tel.insert_many(chunk, ordered=False)
            sent += len(chunk)
        state.bulk_write([UpdateOne({"_id": d["vehicle_id"]}, {"$set": {
            "last_ts": d["ts"], "location": d["location"], "region": d["region"],
            "speed_kmh": d["speed_kmh"], "engine_temp_c": d["engine_temp_c"]}}, upsert=True)
            for d in docs], ordered=False)
    except PyMongoError as e:
        print("WRITE ERROR:", type(e).__name__, flush=True); time.sleep(1)
    el = time.time() - t0
    print(f"{datetime.now():%H:%M:%S} confirmed={sent} rate={sent/el:.0f} msg/s", flush=True)
    if DURATION and el >= DURATION: break
    time.sleep(max(0, INTERVAL - (time.time() - t)))