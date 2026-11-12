import requests

from generator.providers.cache import cache


BASE_URL = "https://router.project-osrm.org/route/v1"

ROUTE_TTL = 86400


def get_route(origin, destination, profile="driving"):

    # origin and destination are (latitude, longitude)

    if profile not in ("driving", "cycling", "walking"):
        raise ValueError("Unsupported routing profile")

    for latitude, longitude in (origin, destination):

        if not -90 <= latitude <= 90:
            raise ValueError("Invalid latitude")

        if not -180 <= longitude <= 180:
            raise ValueError("Invalid longitude")

    # Convert to OSRM longitude,latitude format
    coordinates = (
        f"{origin[1]},{origin[0]};"
        f"{destination[1]},{destination[0]}"
    )

    # Cache key
    cache_key = (
        f"route:{profile}:{coordinates}"
    )

    cached_data = cache.get(cache_key)

    if cached_data is not None:
        return cached_data

    # Build URL
    url = f"{BASE_URL}/{profile}/{coordinates}"

    params = {
        "overview": "full",
        "geometries": "geojson",
        "steps": "true",
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=20
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Routing API request failed: {exc}"
        ) from exc

    # Validate OSRM response
    if data.get("code") != "Ok":
        raise RuntimeError(
            f"OSRM returned: {data.get('code')}"
        )

    routes = data.get("routes", [])

    if not routes:
        raise RuntimeError("No route found")

    route = routes[0]

    geometry = route["geometry"]

    result = {
        "profile": profile,
        "distance_m": route["distance"],
        "duration_s": route["duration"],
        "geometry": geometry,
        "coordinates": geometry["coordinates"],
        "steps": route.get("legs", []),
    }

    cache.set(cache_key, result, ROUTE_TTL)

    return result
