import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from generator.providers.routing import get_route
from generator.providers.weather import get_weather
from generator.providers.poi import get_pois_near_route


def main():

    # Tunis -> Sousse
    origin = (36.8065, 10.1815)
    destination = (35.8256, 10.6369)

    # 1. Calculate road route
    route = get_route(origin, destination)

    print("\nROUTE")
    print("Distance:", route["distance_m"] / 1000, "km")
    print("Duration:", route["duration_s"] / 3600, "hours")

    # 2. Get weather at origin
    weather = get_weather(*origin)

    print("\nWEATHER")
    print("Temperature:", weather["temperature"][0])
    print("Rain:", weather["rain"][0])
    print("Wind:", weather["wind_speed"][0])
    print("Snow:", weather["snowfall"][0])

    # 3. Find POIs along route
    pois = get_pois_near_route(route["coordinates"])

    print("\nPOINTS OF INTEREST")

    for poi in pois:
        print(
            poi["name"],
            poi["category"],
            poi["latitude"],
            poi["longitude"]
        )


if __name__ == "__main__":
    main()
