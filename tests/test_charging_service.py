from app.services.charging_service import OpenChargeMapService


def test_station_normalization():
    service = OpenChargeMapService()

    raw_item = {
        "ID": 12345,
        "UUID": "abc-123",
        "UsageCost": "Ücretli",
        "NumberOfPoints": 2,
        "StatusType": {
            "Title": "Operational",
            "IsOperational": True,
        },
        "OperatorInfo": {
            "Title": "Test Operator"
        },
        "UsageType": {
            "Title": "Public"
        },
        "AddressInfo": {
            "Title": "Test Station",
            "AddressLine1": "Main Street 1",
            "Town": "Ankara",
            "Latitude": 39.92,
            "Longitude": 32.85,
            "Distance": 1.2,
            "DistanceUnit": 1,
        },
        "Connections": [
            {
                "PowerKW": 60,
                "Quantity": 1,
                "ConnectionType": {"Title": "CCS"},
                "CurrentType": {"Title": "DC"},
                "Level": {"IsFastChargeCapable": True},
                "StatusType": {"Title": "Operational"},
            }
        ],
    }

    station = service._normalize_station(raw_item)

    assert station.ocm_id == 12345
    assert station.name == "Test Station"
    assert station.operator == "Test Operator"
    assert station.town == "Ankara"
    assert station.is_operational is True
    assert len(station.connections) == 1
    assert station.connections[0].connection_type == "CCS"
    assert station.connections[0].power_kw == 60.0


def test_find_stations_along_route_deduplicates(monkeypatch):
    service = OpenChargeMapService()

    class DummyStation:
        def __init__(self, ocm_id, distance_km, is_operational=True):
            self.ocm_id = ocm_id
            self.distance_km = distance_km
            self.is_operational = is_operational

    def fake_get_nearby_stations(*args, **kwargs):
        return [
            DummyStation(1001, 2.0, True),
            DummyStation(1002, 3.0, True),
            DummyStation(1001, 1.5, True),
        ]

    monkeypatch.setattr(service, "get_nearby_stations", fake_get_nearby_stations)

    sampled_geometry = [
        (39.90, 32.80),
        (39.85, 32.70),
        (39.80, 32.60),
        (39.75, 32.50),
    ]

    results = service.find_stations_along_route(
        sampled_geometry=sampled_geometry,
        query_every_n_points=2,
        distance_km=5.0,
        max_results_per_query=10,
    )

    ids = [s.ocm_id for s in results]
    assert len(ids) == len(set(ids))
    assert 1001 in ids
    assert 1002 in ids