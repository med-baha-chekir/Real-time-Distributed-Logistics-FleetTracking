"""Test de connexion au Replica Set (livrable semaine 1)."""
import os
import time
from datetime import datetime, timezone

from pymongo import MongoClient, WriteConcern
from pymongo.errors import PyMongoError

URI = os.getenv(
    "MONGO_URI",
    "mongodb://mongo1:27017,mongo2:27017,mongo3:27017/?replicaSet=rs0",
)


def main():
    client = MongoClient(URI, serverSelectionTimeoutMS=10000)

    try:
        hello = client.admin.command("hello")
    except PyMongoError as e:
        print(f"Connexion impossible : {e}")
        raise SystemExit(1)

    print(f"Replica Set : {hello['setName']}")
    print(f"Primaire    : {hello['primary']}")
    print(f"Membres     : {', '.join(hello['hosts'])}")

    # Écriture avec w:"majority", puis mesure de latence
    col = client.fleet.get_collection(
        "healthcheck", write_concern=WriteConcern(w="majority")
    )
    start = time.perf_counter()
    res = col.insert_one({"ts": datetime.now(timezone.utc), "msg": "phase 1 ok"})
    latency_ms = (time.perf_counter() - start) * 1000
    print(f"Écriture w=majority OK (id={res.inserted_id}) en {latency_ms:.1f} ms")

    doc = col.find_one({"_id": res.inserted_id})
    print(f"Lecture OK : {doc}")

    # État des nœuds
    status = client.admin.command("replSetGetStatus")
    for m in status["members"]:
        print(f"  - {m['name']}: {m['stateStr']}")

    client.close()


if __name__ == "__main__":
    main()
