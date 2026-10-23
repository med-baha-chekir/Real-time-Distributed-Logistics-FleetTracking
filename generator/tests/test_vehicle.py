
import math
from datetime import datetime, timezone

from config import MIN_SPEED, MAX_SPEED
from routes import CITIES
from vehicle import Vehicle


def create_sample():
    """Crée un camion et génère une mesure de test."""
    vehicle = Vehicle(1)
    return vehicle.step(5)


def test_tunis_coordinates():
    """Vérifie l'ordre longitude, latitude pour Tunis."""

    lon, lat = CITIES["Tunis"]

    assert math.isclose(lon, 10.1815, abs_tol=0.001)
    assert math.isclose(lat, 36.8065, abs_tol=0.001)


def test_geojson_coordinates_order():
    """Vérifie que les coordonnées générées sont plausibles
    pour la Tunisie : longitude puis latitude."""

    document = create_sample()

    coordinates = document["location"]["coordinates"]

    assert len(coordinates) == 2

    lon, lat = coordinates

    # La longitude tunisienne est approximativement comprise
    # entre 7 et 12 degrés Est.
    assert 7 <= lon <= 12

    # La latitude tunisienne est approximativement comprise
    # entre 30 et 38 degrés Nord.
    assert 30 <= lat <= 38

    assert document["location"]["type"] == "Point"


def test_timestamp_is_datetime():
    """Vérifie que ts est un datetime UTC et non une chaîne."""

    document = create_sample()
    ts = document["ts"]

    assert isinstance(ts, datetime)
    assert not isinstance(ts, str)

    # Vérifie que la date contient un fuseau horaire.
    assert ts.tzinfo is not None

    # Vérifie que le décalage horaire est UTC.
    assert ts.utcoffset() == timezone.utc.utcoffset(ts)


def test_numeric_fields():
    """Vérifie les types des principales mesures."""

    document = create_sample()

    numeric_fields = [
        "speed_kmh",
        "engine_temp_c",
        "fuel_level_pct",
        "fuel_rate_lph",
        "odometer_km",
    ]

    for field in numeric_fields:
        value = document[field]

        # bool est exclu, même si bool est un sous-type de int.
        assert isinstance(value, (int, float)), (
            f"{field} doit être numérique, valeur reçue : {value!r}"
        )
        assert not isinstance(value, bool)
        assert math.isfinite(value)


def test_speed_is_plausible():
    """Vérifie que la vitesse respecte les limites configurées."""

    document = create_sample()
    speed = document["speed_kmh"]

    assert MIN_SPEED <= speed <= MAX_SPEED


def test_fuel_percentage_is_valid():
    """Le niveau de carburant doit rester entre 0 et 100 %."""

    document = create_sample()

    assert 0 <= document["fuel_level_pct"] <= 100


def test_vehicle_identifiers():
    """Vérifie la présence des identifiants du véhicule et du trajet."""

    document = create_sample()

    assert document["vehicle_id"] == "VH-000001"
    assert isinstance(document["trip_id"], str)
    assert document["trip_id"] != ""
