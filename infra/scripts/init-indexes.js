// Index de la collection telemetry (sprint 3), avec mesure de la durée de
// création et de la taille de chaque index.
//
//   bash infra/scripts/init-indexes.sh                 # index du plan (section 7)
//   INDEX_SET=extra bash infra/scripts/init-indexes.sh # + index ajoutés après mesure
//   DB_NAME=fleet_bench bash infra/scripts/init-indexes.sh
//
// Idempotent : un index déjà présent n'est pas recréé (durée affichée : 0).
// À lancer APRÈS la mesure « explain --label before » (report/explain/before/).

const DB_NAME = (typeof process !== "undefined" && process.env.DB_NAME) || "fleet";
const INDEX_SET = (typeof process !== "undefined" && process.env.INDEX_SET) || "plan";
const fleet = db.getSiblingDB(DB_NAME);
const telemetry = fleet.telemetry;

// Index du plan d'exécution (section 7)
const PLAN = [
  { name: "vehicle_ts", key: { vehicle_id: 1, ts: -1 },
    why: "historique d'un camion (requête f)" },
  { name: "region_ts", key: { region: 1, ts: -1 },
    why: "statistiques d'une région sur une période" },
  { name: "ts", key: { ts: -1 },
    why: "fenêtres temporelles (a, b, d, e), heure de référence" },
  { name: "location_2dsphere", key: { location: "2dsphere" },
    why: "requêtes géographiques sur l'historique (zone)" },
];

// Index ajoutés après analyse des mesures « after » (voir report/index.md)
const EXTRA = [
  { name: "overheat_partial", key: { ts: -1, vehicle_id: 1, engine_temp_c: 1 },
    options: { partialFilterExpression: { engine_temp_c: { $gt: 105 } } },
    why: "alertes de surchauffe (d) : index partiel ET couvrant, seulement les ~0,4 % de messages > 105 °C" },
  { name: "ts_location", key: { ts: -1, location: "2dsphere" },
    why: "vitesse dans une zone (géo + fenêtre) : filtre la période ET la zone dans l'index" },
  { name: "ts_covering", key: { ts: -1, region: 1, vehicle_id: 1, speed_kmh: 1, fuel_rate_lph: 1 },
    why: "index couvrant pour a, b et e : servies par l'index seul, sans lire les documents" },
];

const wanted = INDEX_SET === "extra" ? PLAN.concat(EXTRA) : PLAN;
const existing = telemetry.getIndexes().map(i => i.name);
const MB = 1024 * 1024;
const results = [];

print(`[init-indexes] base ${DB_NAME}, ${telemetry.estimatedDocumentCount()} documents, jeu "${INDEX_SET}"`);
for (const idx of wanted) {
  let seconds = 0;
  if (!existing.includes(idx.name)) {
    const t0 = Date.now();
    telemetry.createIndex(idx.key, Object.assign({ name: idx.name }, idx.options || {}));
    seconds = (Date.now() - t0) / 1000;
  }
  results.push({ name: idx.name, key: idx.key, seconds, why: idx.why });
}

// Tailles après construction (sur le nœud interrogé, le primaire)
const sizes = telemetry.stats().indexSizes;
print("index".padEnd(24) + "création (s)".padStart(14) + "taille (Mo)".padStart(13) + "   clé");
for (const r of results) {
  r.size_mb = +(sizes[r.name] / MB).toFixed(1);
  print(r.name.padEnd(24) + String(r.seconds.toFixed(1)).padStart(14) +
        String(r.size_mb).padStart(13) + "   " + JSON.stringify(r.key));
}
const total = Object.values(sizes).reduce((a, b) => a + b, 0) / MB;
print(`[init-indexes] taille totale des index de telemetry : ${total.toFixed(1)} Mo ` +
      `(données sur disque : ${(telemetry.stats().storageSize / MB).toFixed(1)} Mo)`);
print("JSON " + JSON.stringify(results));
