from models.route_evaluation_model.routing.rail_router import (
    RailRouter,
    Stop,
    CompositionParams,
    InfraParams,
)
import logging
import time

router = RailRouter()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# --- composition ---
composition = CompositionParams(
    comp_id="NJ-3.1",
    weight_gross_t=566.6,
    max_speed_kmh=230,
    hsr_allowed=True,
    energy_factor_weight=0.0001675,
    energy_factor_speed=0.0151229,
    energy_factor_terrain=0.0345454,
    min_boarding_time_h=2 / 60,  # 2 minutes
    min_alighting_time_h=2 / 60,  # 2 minutes
)

# --- infrastructure params ---
infra = {
    "_default": InfraParams(
        country_code="_default",
        tac_eur_train_km=2.0,  # EU average estimate
        parking_eur_day=50.0,
        energy_price_eur_kwh=0.25,
        terrain_score=50,
        hsr_allowed=True,
        min_boarding_time_h=2 / 60,
        min_alighting_time_h=2 / 60,
        buffer_quota_per=0.1,
    ),
    "DE": InfraParams(
        country_code="DE",
        tac_eur_train_km=4.5,
        parking_eur_day=50.0,
        energy_price_eur_kwh=0.25,
        terrain_score=30,
        hsr_allowed=True,
        min_boarding_time_h=2 / 60,
        min_alighting_time_h=2 / 60,
        buffer_quota_per=0.1,
    ),
    "AT": InfraParams(
        country_code="AT",
        tac_eur_train_km=1.36,
        parking_eur_day=50.0,
        energy_price_eur_kwh=0.25,
        terrain_score=90,
        hsr_allowed=True,
        min_boarding_time_h=2 / 60,
        min_alighting_time_h=2 / 60,
        buffer_quota_per=0.1,
    ),
    "FR": InfraParams(
        country_code="FR",
        tac_eur_train_km=3.5,
        parking_eur_day=50.0,
        energy_price_eur_kwh=0.20,
        terrain_score=40,
        hsr_allowed=False,
        min_boarding_time_h=2 / 60,
        min_alighting_time_h=2 / 60,
        buffer_quota_per=0.08,
    ),
}

# --- stops ---
stops = [
    Stop(
        stop_id="hamburg_hbf",
        name="Hamburg Hbf",
        lat=53.5535,
        lon=10.0045,
        country_code="DE",
        stop_type="boarding",
    ),
    Stop(
        stop_id="paris_est",
        name="Paris Est",
        lat=48.8768,
        lon=2.3588,
        country_code="FR",
        stop_type="both",
    ),
    Stop(
        stop_id="wien_hbf",
        name="Wien Hbf",
        lat=48.1853,
        lon=16.3756,
        country_code="AT",
        stop_type="alighting",
    ),
]

departure_time_h = 21.0  # 21:00

print("=== Test 1: no overrides ===")
t0 = time.perf_counter()
result = router.route(stops, composition, infra, departure_time_h)
print(f"Time: {time.perf_counter() - t0:.2f}s")
print(result)
