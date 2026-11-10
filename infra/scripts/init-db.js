// Création des collections de la base "fleet" avec validation de schéma.
// Idempotent : peut être relancé sans erreur (le validateur est mis à jour).
//
// Lancement (depuis la racine du dépôt, sur le primaire) :
//   bash infra/scripts/init-db.sh
//
// Choix volontaire : AUCUN index secondaire sur telemetry ici.
// Les index sont créés au sprint 3 pour mesurer explain() avant / après.

const fleet = db.getSiblingDB("fleet");

// Nombre (int, long, double ou decimal)
const NUM = { bsonType: ["double", "int", "long", "decimal"] };

// Point GeoJSON limité à la Tunisie : [longitude, latitude].
// Les bornes détectent une inversion lat/lng (lat ~ 36 est hors de [7, 12]).
const TUNISIA_POINT = {
  bsonType: "object",
  required: ["type", "coordinates"],
  properties: {
    type: { enum: ["Point"] },
    coordinates: {
      bsonType: "array",
      minItems: 2,
      maxItems: 2,
      items: [
        { bsonType: ["double", "int"], minimum: 7, maximum: 12 },   // longitude
        { bsonType: ["double", "int"], minimum: 30, maximum: 38 },  // latitude
      ],
    },
  },
};

const schemas = {
  vehicles: {
    $jsonSchema: {
      bsonType: "object",
      required: ["_id", "model", "capacity_t", "home_region", "status"],
      properties: {
        _id: { bsonType: "string", pattern: "^VH-[0-9]{6}$" },
        model: { bsonType: "string" },
        capacity_t: NUM,
        home_region: { bsonType: "string" },
        status: { enum: ["active", "maintenance", "inactive"] },
        created_at: { bsonType: "date" },
      },
    },
  },

  telemetry: {
    $jsonSchema: {
      bsonType: "object",
      // TODO (générateur v2) : ajouter "region" aux champs obligatoires
      // dès que le générateur le produit.
      required: ["vehicle_id", "ts", "location", "speed_kmh"],
      properties: {
        vehicle_id: { bsonType: "string", pattern: "^VH-[0-9]{6}$" },
        ts: { bsonType: "date" },
        location: TUNISIA_POINT,
        region: { bsonType: "string" },
        trip_id: { bsonType: "string" },
        route_id: { bsonType: "string" },
        speed_kmh: { bsonType: ["double", "int"], minimum: 0, maximum: 160 },
        fuel_level_pct: { bsonType: ["double", "int"], minimum: 0, maximum: 100 },
        fuel_rate_lph: { bsonType: ["double", "int"], minimum: 0 },
        engine_temp_c: NUM,
        odometer_km: { bsonType: ["double", "int"], minimum: 0 },
      },
    },
  },

  vehicle_state: {
    $jsonSchema: {
      bsonType: "object",
      required: ["_id", "last_ts", "location"],
      properties: {
        _id: { bsonType: "string", pattern: "^VH-[0-9]{6}$" },
        last_ts: { bsonType: "date" },
        location: TUNISIA_POINT,
        region: { bsonType: "string" },
        speed_kmh: NUM,
        engine_temp_c: NUM,
      },
    },
  },
};

const existing = fleet.getCollectionNames();

for (const [name, validator] of Object.entries(schemas)) {
  const options = {
    validator,
    validationLevel: "strict",
    validationAction: "error",
  };

  if (existing.includes(name)) {
    fleet.runCommand({ collMod: name, ...options });
    print(`[init-db] ${name} : existe déjà, validateur mis à jour`);
  } else {
    fleet.createCollection(name, options);
    print(`[init-db] ${name} : créée`);
  }
}

// vehicle_state est petite (1 doc par camion) et sert à la carte temps réel :
// son index 2dsphere est créé dès maintenant (createIndex est idempotent).
fleet.vehicle_state.createIndex(
  { location: "2dsphere" },
  { name: "location_2dsphere" }
);
print("[init-db] vehicle_state : index 2dsphere OK");

print("[init-db] Collections : " + fleet.getCollectionNames().sort().join(", "));
