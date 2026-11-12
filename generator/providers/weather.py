
import requests

from generator.providers.cache import cache


BASE_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_TTL = 1800

WEATHER_VARIABLES = [
    "temperature_2m",
    "rain",
    "wind_speed_10m",
    "snowfall",
]


def get_weather(latitude, longitude):

    # 1. Validate coordinates
    if not -90 <= latitude <= 90:
        raise ValueError("Invalid latitude")

    if not -180 <= longitude <= 180:
        raise ValueError("Invalid longitude")

    # 2. Build cache key
    cache_key = (
        f"weather:{latitude:.4f}:{longitude:.4f}"
    )

    # 3. Check cache
    cached_data = cache.get(cache_key)

    if cached_data is not None:
        return cached_data

    # 4. Build API parameters
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(WEATHER_VARIABLES),
        "forecast_days": 1,
        "timezone": "auto",
    }

    # 5. Send HTTP request
    try:
        response = requests.get(
            BASE_URL,
            params=params,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Weather API request failed: {exc}"
        ) from exc

    # 6. Extract weather information
    hourly = data.get("hourly")

    if not hourly:
        raise RuntimeError("Invalid weather API response")

    # 7. Normalize response
    result = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": data.get("timezone"),
        "time": hourly["time"],
        "temperature": hourly["temperature_2m"],
        "rain": hourly["rain"],
        "wind_speed": hourly["wind_speed_10m"],
        "snowfall": hourly["snowfall"],
    }

    # 8. Save in cache
    cache.set(cache_key, result, WEATHER_TTL)

    return result
