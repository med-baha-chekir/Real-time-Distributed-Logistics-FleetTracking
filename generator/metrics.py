
import time


class Metrics:
    def __init__(self):
        self.start_time = time.perf_counter()
        self.messages_sent = 0
        self.errors = 0

    def record_success(self, count):
        # Ajoute le nombre de documents effectivement insérés
        self.messages_sent += count

    def record_error(self):
        self.errors += 1

    def report(self):
        # Évite une division par zéro
        elapsed = max(time.perf_counter() - self.start_time, 0.001)

        # Débit moyen depuis le début du programme
        rate = self.messages_sent / elapsed

        print(
            f"Messages insérés : {self.messages_sent} | "
            f"Erreurs : {self.errors} | "
            f"Temps : {elapsed:.1f} s | "
            f"Débit moyen : {rate:.1f} msg/s",
            flush=True,
        )
