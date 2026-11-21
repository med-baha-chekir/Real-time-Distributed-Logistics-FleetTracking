"""Compteurs du générateur : documents insérés, erreurs, débit, latence par lot."""

import statistics
import time


class Metrics:
    def __init__(self, label=""):
        self.label = label
        self.start_time = time.perf_counter()
        self.messages_sent = 0
        self.errors = 0
        self.retries = 0
        self.batch_latencies_ms = []      # insert_many seul (mesure du plan : < 100 ms)
        self.state_latencies_ms = []      # mise à jour de vehicle_state

    def record_batch(self, inserted, latency_ms, state_latency_ms=None):
        self.messages_sent += inserted
        self.batch_latencies_ms.append(latency_ms)
        if state_latency_ms is not None:
            self.state_latencies_ms.append(state_latency_ms)

    def record_error(self):
        self.errors += 1

    def record_retry(self):
        self.retries += 1

    def elapsed(self):
        return max(time.perf_counter() - self.start_time, 0.001)

    def summary(self):
        lat = sorted(self.batch_latencies_ms)
        return {
            "label": self.label,
            "docs": self.messages_sent,
            "errors": self.errors,
            "retries": self.retries,
            "elapsed_s": round(self.elapsed(), 2),
            "throughput_docs_s": round(self.messages_sent / self.elapsed(), 1),
            "batches": len(lat),
            "latency_ms_mean": round(statistics.mean(lat), 1) if lat else None,
            "latency_ms_p95": round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None,
            "state_latency_ms_mean": (round(statistics.mean(self.state_latencies_ms), 1)
                                      if self.state_latencies_ms else None),
        }

    def report(self):
        s = self.summary()
        lat = f"{s['latency_ms_mean']} ms" if s["latency_ms_mean"] is not None else "-"
        if s["state_latency_ms_mean"] is not None:
            lat += f" (+ vehicle_state {s['state_latency_ms_mean']} ms)"
        print(
            f"{self.label}Messages insérés : {s['docs']} | Erreurs : {s['errors']} | "
            f"Reprises : {s['retries']} | Temps : {s['elapsed_s']:.1f} s | "
            f"Débit moyen : {s['throughput_docs_s']:.1f} msg/s | Latence insert_many : {lat}",
            flush=True,
        )
