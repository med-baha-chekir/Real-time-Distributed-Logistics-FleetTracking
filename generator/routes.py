
# Coordonnées GPS des villes : (longitude, latitude)

CITIES = {
    "Tunis": (10.1815, 36.8065),
    "Bizerte": (9.8739, 37.2746),
    "Nabeul": (10.7357, 36.4561),
    "Sousse": (10.6411, 35.8256),
    "Monastir": (10.8262, 35.7770),
    "Kairouan": (10.0963, 35.6781),
    "Sfax": (10.7600, 34.7406),
    "Gabes": (10.0982, 33.8815),
    "Gafsa": (8.7757, 34.4250),
    "Kasserine": (8.8365, 35.1676),
    "Beja": (9.1844, 36.7256),
    "Kef": (8.7049, 36.1742),
}

# Version simplifiée : chaque itinéraire possède
# un point de départ, un waypoint intermédiaire
# et un point d'arrivée.
# Les waypoints sont illustratifs, pas des routes réelles.

ROUTES = [
    {
        "route_id": "R01",
        "origin": "Tunis",
        "destination": "Sousse",
        "waypoints": [
            CITIES["Tunis"],
            (10.45, 36.45),
            CITIES["Sousse"],
        ],
    },
    {
        "route_id": "R02",
        "origin": "Tunis",
        "destination": "Sfax",
        "waypoints": [
            CITIES["Tunis"],
            CITIES["Sousse"],
            CITIES["Sfax"],
        ],
    },
    {
        "route_id": "R03",
        "origin": "Tunis",
        "destination": "Bizerte",
        "waypoints": [
            CITIES["Tunis"],
            (10.05, 37.00),
            CITIES["Bizerte"],
        ],
    },
    {
        "route_id": "R04",
        "origin": "Tunis",
        "destination": "Nabeul",
        "waypoints": [
            CITIES["Tunis"],
            (10.50, 36.65),
            CITIES["Nabeul"],
        ],
    },
    {
        "route_id": "R05",
        "origin": "Sousse",
        "destination": "Monastir",
        "waypoints": [
            CITIES["Sousse"],
            (10.75, 35.80),
            CITIES["Monastir"],
        ],
    },
    {
        "route_id": "R06",
        "origin": "Sousse",
        "destination": "Kairouan",
        "waypoints": [
            CITIES["Sousse"],
            (10.35, 35.75),
            CITIES["Kairouan"],
        ],
    },
    {
        "route_id": "R07",
        "origin": "Sfax",
        "destination": "Gabes",
        "waypoints": [
            CITIES["Sfax"],
            (10.45, 34.30),
            CITIES["Gabes"],
        ],
    },
    {
        "route_id": "R08",
        "origin": "Sfax",
        "destination": "Gafsa",
        "waypoints": [
            CITIES["Sfax"],
            (9.70, 34.55),
            CITIES["Gafsa"],
        ],
    },
    {
        "route_id": "R09",
        "origin": "Tunis",
        "destination": "Beja",
        "waypoints": [
            CITIES["Tunis"],
            (9.65, 36.65),
            CITIES["Beja"],
        ],
    },
    {
        "route_id": "R10",
        "origin": "Beja",
        "destination": "Kef",
        "waypoints": [
            CITIES["Beja"],
            (8.95, 36.45),
            CITIES["Kef"],
        ],
    },
    {
        "route_id": "R11",
        "origin": "Kairouan",
        "destination": "Sfax",
        "waypoints": [
            CITIES["Kairouan"],
            (10.45, 35.15),
            CITIES["Sfax"],
        ],
    },
    {
        "route_id": "R12",
        "origin": "Gabes",
        "destination": "Gafsa",
        "waypoints": [
            CITIES["Gabes"],
            (9.40, 34.10),
            CITIES["Gafsa"],
        ],
    },
]
