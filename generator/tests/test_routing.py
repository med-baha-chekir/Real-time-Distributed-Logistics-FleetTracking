
from generator.providers.routing import get_route


def test_routing_provider():

    origin = (36.8065, 10.1815)
    destination = (35.8256, 10.6369)

    result = get_route(origin, destination)

    assert result["distance_m"] > 0
    assert result["duration_s"] > 0

    assert result["geometry"]["type"] == "LineString"

    assert len(result["coordinates"]) > 2

    # OSRM returns longitude, latitude
    longitude, latitude = result["coordinates"][0]

    assert -180 <= longitude <= 180
    assert -90 <= latitude <= 90
