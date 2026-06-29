"""
test_run_model.py
=================
End-to-end test of the full night train model pipeline.
"""

import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from models.route_evaluation_model.run_model import run

# --- config ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "route_evaluation_model", "model_config.yml")

# --- run pipeline ---
result = run(
    config_path=CONFIG_PATH,
    stop_inputs=[
        ("Wien Hbf", "boarding"),
        ("Salzburg Hbf", "both"),
        ("München Hbf", "alighting"),
    ],
    composition_id="NJ-3.1",
    departure_time_h=21.0,
    utilization_seat=0.6,
    utilization_couchette=0.7,
    utilization_sleeper=0.8,
    avg_fare_seat=49.0,
    avg_fare_couchette=79.0,
    avg_fare_sleeper=129.0,
    operating_days_year=365,
)

print(result.summary())
