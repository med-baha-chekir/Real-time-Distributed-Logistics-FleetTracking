
from generator.providers.poi import (
    sample_route,
    build_overpass_query,
    normalize_poi,
)


def test_sample_route():

    coordinates = [
        [10.0, 36.0],
        [10.1, 36.1],
        [10.2, 36.2],
        [10.3, 36.3],
        [10.4, 36.4],
    ]

    result = sample_route(coordinates, max_points=3)

    assert len(result) == 3
    assert result[0] == coordinates[0]
    assert result[-1] == coordinates[-1]


def test_overpass_query():

    coordinates = [
        [10.1815, 36.8065],
        [10.6369, 35.8256],
    ]

    query = build_overpass_query(coordinates)

    assert 'amenity"="fuel' in query
    assert "rest_area" in query
    assert "harbour" in query


def test_normalize_fuel_station():

    element = {
        "type": "node",
        "id": 123,
        "lat": 36.8,
        "lon": 10.18,
        "tags": {
            "amenity": "fuel",
            "name": "Test Station"
        }
    }

    result = normalize_poi(element)

    assert result["category"] == "fuel"
    assert result["name"] == "Test Station"
    assert result["latitude"] == 36.8
