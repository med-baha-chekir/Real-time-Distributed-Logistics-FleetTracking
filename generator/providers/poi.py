
import hashlib
import requests

from generator.providers.cache import cache


OVERPASS_URL = "https://overpass-api.de/api/interpreter"

POI_TTL = 86400
SEARCH_RADIUS = 500
MAX_ROUTE_POINTS = 20


def sample_route(coordinates, max_points=MAX_ROUTE_POINTS):
    """
    Select representative coordinates from a route.

    Input: [[longitude, latitude], ...]
    Output: [[longitude, latitude], ...]
    """

    if not coordinates:
        raise ValueError("Route coordinates are empty")

    if len(coordinates) <= max_points:
        return coordinates

    indexes = [
        round(i * (len(coordinates) - 1) / (max_points - 1))
        for i in range(max_points)
    ]

    return [coordinates[i] for i in indexes]


def build_overpass_query(coordinates, radius=SEARCH_RADIUS):

    # OSRM: longitude, latitude
    # Overpass: latitude, longitude

    route_points = ",".join(
        f"{latitude},{longitude}"
        for longitude, latitude in coordinates
    )

    query = f"""
    [out:json][timeout:25];

    (
        nwr["amenity"="fuel"]
        (around:{radius},{route_points});

        nwr["highway"="rest_area"]
        (around:{radius},{route_points});

        nwr["amenity"="parking"]
        (around:{radius},{route_points});

        nwr["harbour"="yes"]
        (around:{radius},{route_points});
    );

    out center;
    """

    return query


def normalize_poi(element):

    tags = element.get("tags", {})

    # Nodes have direct coordinates.
    # Ways and relations generally have a center
    # because we requested "out center".

    if element["type"] == "node":
        latitude = element.get("lat")
        longitude = element.get("lon")
    else:
        center = element.get("center", {})
        latitude = center.get("lat")
        longitude = center.get("lon")

    if latitude is None or longitude is None:
        return None

    if tags.get("amenity") == "fuel":
        category = "fuel"

    elif tags.get("highway") == "rest_area":
        category = "rest_area"

    elif tags.get("amenity") == "parking":
        category = "parking"

    elif tags.get("harbour") == "yes":
        category = "port"

    else:
        return None

    return {
        "id": f"{element['type']}/{element['id']}",
        "name": tags.get("name", "Unnamed"),
        "category": category,
        "latitude": latitude,
        "longitude": longitude,
        "tags": tags,
    }


def get_pois_near_route(route_coordinates, radius=SEARCH_RADIUS):

    if radius <= 0:
        raise ValueError("Radius must be positive")

    # 1. Simplify route for API query
    points = sample_route(route_coordinates)

    # 2. Generate cache key
    route_string = str(points)

    route_hash = hashlib.sha256(
        route_string.encode()
    ).hexdigest()

    cache_key = f"pois:{route_hash}:{radius}"

    # 3. Check cache
    cached_data = cache.get(cache_key)

    if cached_data is not None:
        return cached_data

    # 4. Build query
    query = build_overpass_query(points, radius)

    # 5. Request Overpass
    try:
        response = requests.post(
            OVERPASS_URL,
            data={"data": query},
            timeout=40
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Overpass API request failed: {exc}"
        ) from exc

    # 6. Normalize results
    pois = []

    for element in data.get("elements", []):

        poi = normalize_poi(element)

        if poi is not None:
            pois.append(poi)

    # 7. Remove duplicate OSM elements
    unique_pois = {
        poi["id"]: poi
        for poi in pois
    }

    result = list(unique_pois.values())

    # 8. Cache
    cache.set(cache_key, result, POI_TTL)

    return result
