"""
seed_proposals.py
=================
Seed data and seeder for the proposals schema.

Tables covered (in insert order):
  proposals.services
  proposals.calendar
  proposals.calendar_dates
  proposals.shapes
  proposals.routes
  proposals.trips
  proposals.stop_times
"""

# ============================================================
# Seed data
# ============================================================

SERVICES = [
    {"service_id": "NJ-BER-VIE-DAILY"},
]

CALENDAR = [
    {
        "service_id": "NJ-BER-VIE-DAILY",
        "monday": True, "tuesday": True, "wednesday": True, "thursday": True,
        "friday": True, "saturday": True, "sunday": True,
        "start_date": "2026-12-13",
        "end_date":   "2027-12-11",
    },
]

CALENDAR_DATES = [
    {"service_id": "NJ-BER-VIE-DAILY", "date": "2026-12-24", "exception_type": 2},
]

SHAPES = [
    {
        "shape_id":  "NJ-BER-VIE-SHAPE",
        "geometry":  {
            "type": "LineString",
            "coordinates": [[13.369, 52.525], [13.732, 51.040], [16.376, 48.185]],
        },
        "length_km": 683.4,
    },
]

ROUTES = [
    {
        "route_id":         "NJ-BER-VIE",
        "agency_id":        None,
        "route_short_name": "NJ 470",
        "route_long_name":  "Berlin Hbf - Vienna Hbf",
        "route_type":       105,
    },
]

TRIPS = [
    {
        "trip_id":              "NJ-BER-VIE-OUTBOUND",
        "route_id":             "NJ-BER-VIE",
        "service_id":           "NJ-BER-VIE-DAILY",
        "shape_id":             "NJ-BER-VIE-SHAPE",
        "trip_headsign":        "Wien Hbf",
        "direction_id":         0,
        "composition_type_id":  "STD-3.1",
    },
]

STOP_TIMES = [
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 1, "stop_id": "DE_BERLIN_HBF",  "arrival_time": "21:04:00", "departure_time": "21:04:00"},
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 2, "stop_id": "DE_DRESDEN_HBF", "arrival_time": "22:47:00", "departure_time": "22:52:00"},
    {"trip_id": "NJ-BER-VIE-OUTBOUND", "stop_sequence": 3, "stop_id": "AT_WIEN_HBF",    "arrival_time": "30:30:00", "departure_time": "30:30:00"},
]


# ============================================================
# Seeder
# ============================================================

def seed_proposals(cur, insert_rows) -> None:
    """Seed all proposals tables in dependency order."""
    print("Seeding proposals.services...")
    insert_rows(cur, "proposals.services",       SERVICES)

    print("Seeding proposals.calendar...")
    insert_rows(cur, "proposals.calendar",       CALENDAR)
    insert_rows(cur, "proposals.calendar_dates", CALENDAR_DATES)

    print("Seeding proposals.shapes...")
    insert_rows(cur, "proposals.shapes",         SHAPES)

    print("Seeding proposals.routes + trips + stop_times...")
    insert_rows(cur, "proposals.routes",         ROUTES)
    insert_rows(cur, "proposals.trips",          TRIPS)
    insert_rows(cur, "proposals.stop_times",     STOP_TIMES)