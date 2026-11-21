"""Tests des itinéraires (géométrie, régions, stations, chargement)."""

import json

from generator.geo import distance_km, nearest_city
from generator.route_network import Route, load_routes
from generator.routes import CITIES, ROUTES


def simple_route(stops=None):
    pts = [CITIES["Tunis"], (10.45, 36.45), CITIES["Sousse"]]
    return Route("T1", "Tunis", "Sousse", pts, [90.0, 50.0], fuel_stops=stops)


def test_distance_and_nearest_city():
    d = distance_km(CITIES["Tunis"], CITIES["Sousse"])
    assert 110 < d < 125                                  # vol d'oiseau ~ 116 km
    assert nearest_city(CITIES["Sfax"]) == "Sfax"
    assert nearest_city((10.19, 36.80)) == "Tunis"


def test_position_at_ends_and_middle():
    r = simple_route()
    assert r.position_at(0) == CITIES["Tunis"]
    end = r.position_at(r.length_km)
    assert abs(end[0] - CITIES["Sousse"][0]) < 1e-9 and abs(end[1] - CITIES["Sousse"][1]) < 1e-9
    assert r.position_at(r.cum_km[1]) == (10.45, 36.45)


def test_speed_and_region_per_segment():
    r = simple_route()
    assert r.speed_at(1) == 90.0
    assert r.speed_at(r.length_km - 1) == 50.0
    assert r.region_at(0.5) == "Tunis"
    assert r.region_at(r.length_km - 0.5) == "Sousse"


def test_next_fuel_stop_both_directions():
    r = simple_route(stops=[20.0, 80.0])
    assert r.next_fuel_stop(10, +1) == 20.0
    assert r.next_fuel_stop(50, +1) == 80.0
    assert r.next_fuel_stop(90, +1) is None
    assert r.next_fuel_stop(50, -1) == 20.0
    assert r.next_fuel_stop(10, -1) is None


def test_fallback_when_file_missing(tmp_path):
    routes = load_routes(str(tmp_path / "absent.json"))
    assert len(routes) == len(ROUTES)
    assert all(r.source == "simplified" for r in routes)


def test_loads_precomputed_file(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text(json.dumps({"routes": [{
        "route_id": "R01", "origin": "Tunis", "destination": "Sousse",
        "points": [list(CITIES["Tunis"]), [10.3, 36.5], list(CITIES["Sousse"])],
        "seg_speed_kmh": [100.0, 40.0], "fuel_stops_km": [12.5],
    }]}), encoding="utf-8")
    routes = load_routes(str(path))
    assert routes[0].source == "osrm"
    assert routes[0].fuel_stops_km == [12.5]


def test_repository_routes_follow_real_roads():
    """Le fichier versionné contient des tracés OSRM (bien plus de 3 points)."""
    routes = load_routes()
    if routes[0].source != "osrm":
        return  # fichier absent : rien à vérifier
    assert len(routes) == len(ROUTES)
    for r in routes:
        assert len(r.points) > 100
        assert all(0 < s < 150 for s in r.seg_speed)
        # Une route est plus longue que le vol d'oiseau, mais pas absurdement
        crow = distance_km(CITIES[r.origin], CITIES[r.destination])
        assert crow < r.length_km < 2.5 * crow
