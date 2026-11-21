"""Tests du producteur avec une fausse base (pas de MongoDB)."""

from datetime import datetime, timedelta, timezone

from pymongo.errors import AutoReconnect, BulkWriteError

from generator import producer as producer_mod
from generator.producer import Producer, parse_write_concern


class FakeResult:
    def __init__(self, n):
        self.inserted_ids = list(range(n))


class FakeCollection:
    def __init__(self, fail_times=0):
        self.docs, self.ops, self.fail_times = [], [], fail_times

    def insert_many(self, docs, ordered=False):
        if self.fail_times:
            self.fail_times -= 1
            raise AutoReconnect("primaire en cours d'élection")
        self.docs.extend(docs)
        return FakeResult(len(docs))

    def bulk_write(self, ops, ordered=False):
        self.ops.extend(ops)


class FakeDB:
    def __init__(self, telemetry=None):
        self.colls = {"telemetry": telemetry or FakeCollection(),
                      "vehicle_state": FakeCollection(), "vehicles": FakeCollection()}

    def get_collection(self, name, write_concern=None):
        self.wc = write_concern
        return self.colls[name]


SETTINGS = {"batch_size": 50, "interval": 5.0, "duration": 0,
            "write_concern": "majority", "seed": 42}


def test_parse_write_concern():
    assert parse_write_concern("majority").document == {"w": "majority"}
    assert parse_write_concern("1").document == {"w": 1}


def test_backfill_timeline_and_counts():
    db = FakeDB()
    p = Producer(db, range(1, 121), SETTINGS)
    start = datetime(2026, 11, 21, 7, 0, tzinfo=timezone.utc)
    summary = p.run_backfill(start, steps=10)

    docs = db.colls["telemetry"].docs
    assert summary["docs"] == len(docs) == 120 * 10
    assert summary["errors"] == 0
    assert min(d["ts"] for d in docs) == start
    assert max(d["ts"] for d in docs) == start + timedelta(seconds=9 * 5)
    assert summary["batches"] == 10 * 3                  # 120 docs / lots de 50


def test_vehicle_state_gets_last_position_of_each_truck():
    db = FakeDB()
    p = Producer(db, range(1, 31), SETTINGS)
    p.run_backfill(datetime(2026, 11, 21, tzinfo=timezone.utc), steps=3)
    ops = db.colls["vehicle_state"].ops
    last = {}
    for op in ops:
        last[op._filter["_id"]] = op._doc["$set"]
    assert len(last) == 30
    assert all(op._upsert for op in ops)
    assert {"last_ts", "location", "region", "speed_kmh", "engine_temp_c"} <= set(
        next(iter(last.values())))


def test_seed_vehicles_upserts_one_doc_per_truck():
    db = FakeDB()
    p = Producer(db, range(1, 26), SETTINGS)
    p.seed_vehicles(datetime(2026, 11, 21, tzinfo=timezone.utc))
    ops = db.colls["vehicles"].ops
    assert len(ops) == 25
    assert {op._filter["_id"] for op in ops} == {f"VH-{n:06d}" for n in range(1, 26)}


def test_retry_during_failover(monkeypatch):
    monkeypatch.setattr(producer_mod.time, "sleep", lambda s: None)
    db = FakeDB(telemetry=FakeCollection(fail_times=2))
    p = Producer(db, range(1, 11), SETTINGS)
    summary = p.run_backfill(datetime(2026, 11, 21, tzinfo=timezone.utc), steps=1)
    assert summary["docs"] == 10
    assert summary["retries"] == 2
    assert summary["errors"] == 0


def test_duplicates_from_a_retry_are_not_errors():
    class DupCollection(FakeCollection):
        def insert_many(self, docs, ordered=False):
            raise BulkWriteError({"nInserted": 7, "writeErrors": [
                {"code": 11000, "errmsg": "E11000 duplicate key"} for _ in range(3)]})

    db = FakeDB(telemetry=DupCollection())
    p = Producer(db, range(1, 11), SETTINGS)
    summary = p.run_backfill(datetime(2026, 11, 21, tzinfo=timezone.utc), steps=1)
    assert summary["docs"] == 10
    assert summary["errors"] == 0


def test_validation_failure_is_reported():
    class RejectCollection(FakeCollection):
        def insert_many(self, docs, ordered=False):
            raise BulkWriteError({"nInserted": 0, "writeErrors": [
                {"code": 121, "errmsg": "Document failed validation"}]})

    db = FakeDB(telemetry=RejectCollection())
    p = Producer(db, range(1, 6), SETTINGS)
    summary = p.run_backfill(datetime(2026, 11, 21, tzinfo=timezone.utc), steps=1)
    assert summary["errors"] == 1
