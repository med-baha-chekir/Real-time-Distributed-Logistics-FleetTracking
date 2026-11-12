
from generator.providers.weather import get_weather


def test_weather_provider():

    result = get_weather(
        latitude=36.8065,
        longitude=10.1815
    )

    assert "temperature" in result
    assert "rain" in result
    assert "wind_speed" in result
    assert "snowfall" in result

    assert len(result["time"]) > 0

    assert len(result["temperature"]) == len(result["time"])
