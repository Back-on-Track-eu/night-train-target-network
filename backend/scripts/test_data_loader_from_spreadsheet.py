import logging
from adapters.data_loader_from_spreadsheet import SheetDataLoader

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "route_evaluation_model", "model_config.yml")

# =============================================================
# PHASE 1 — load all sheets from Google Sheets (once)
# =============================================================
print("\n=== Phase 1: Loading sheets from Google Sheets ===")
loader = SheetDataLoader(CONFIG_PATH)
loader.load_all()

# =============================================================
# PHASE 2 — build typed collections from cache
# =============================================================
print("\n=== Phase 2: Building typed collections ===")
compositions = loader.build_all_compositions()
infra        = loader.build_all_infra()
stop_params  = loader.build_all_stop_params(["Wien Hbf", "Salzburg Hbf", "München Hbf"])
demand       = loader.build_all_demand()
print(f"  compositions: {len(compositions)}")
print(f"  infra:        {len(infra)}")
print(f"  stop_params:  {len(stop_params)}")
print(f"  demand:       {len(demand)}")

# =============================================================
# PHASE 3 — verify collection contents
# =============================================================

# --- compositions ---
print("\n=== Compositions ===")
for comp_id, c in compositions.all().items():
    print(f"  {comp_id:15s}  {c.comp_description:30s}  "
          f"{c.seats_total}s / {c.couchettes_total}c / {c.sleepers_total}sl  "
          f"density: {c.seat_density:.4f} / {c.couchette_density:.4f} / {c.sleeper_density:.4f}")

print("\n  --- NJ-3.1 cost params ---")
nj = compositions.get("NJ-3.1")
if nj:
    print(f"  purchase_loco_eur:       {nj.purchase_loco_eur:,.0f} €")
    print(f"  purchase_coach_eur:      {nj.purchase_coach_eur:,.0f} €")
    print(f"  loco_avail_per:          {nj.loco_avail_per:.0%}")
    print(f"  coach_avail_per:         {nj.coach_avail_per:.0%}")
    print(f"  loco_amort_years:        {nj.loco_amort_years}")
    print(f"  coach_amort_years:       {nj.coach_amort_years}")
    print(f"  financing_quota_per:     {nj.financing_quota_per:.2%}")
    print(f"  fix_overhead_quota_per:  {nj.fix_overhead_quota_per:.2%}")
    print(f"  cleaning_eur_day:        {nj.cleaning_services_eur_day:,.2f} €")
    print(f"  shunting_eur_day:        {nj.shunting_eur_day:,.2f} €")
    print(f"  loco_maint_eur_km:       {nj.loco_maint_eur_km:.4f} €/km")
    print(f"  coach_maint_eur_km:      {nj.coach_maint_eur_km:.4f} €/km")
    print(f"  driver_costs_eur_h:      {nj.driver_costs_eur_h} €/h")
    print(f"  crew_costs_eur_h:        {nj.crew_costs_eur_h} €/h")
    print(f"  driver_overhead_h:       {nj.driver_overhead_h:.4f}h ({nj.driver_overhead_h*60:.0f} min)")
    print(f"  crew_overhead_h:         {nj.crew_overhead_h:.4f}h ({nj.crew_overhead_h*60:.0f} min)")
    print(f"  svc_stockings_seat_per:  {nj.svc_stockings_seat_per:.2%}")
    print(f"  svc_stockings_couch_per: {nj.svc_stockings_couchette_per:.2%}")
    print(f"  svc_stockings_sleep_per: {nj.svc_stockings_sleeper_per:.2%}")
    print(f"  var_overhead_per:        {nj.var_overhead_per:.2%}")
    print(f"  ebit_margin_per:         {nj.ebit_margin_per:.2%}")

# --- infra ---
print("\n=== Infrastructure ===")
for cc in ["AT", "DE", "FR", "BE", "_default"]:
    ip = infra.get(cc)
    if ip:
        print(f"  [{cc:8s}]  tac={ip.tac_eur_train_km:.2f}  "
              f"energy={ip.energy_price_eur_kwh:.2f}  "
              f"terrain={ip.terrain_score:.0f} ({ip.terrain_category:12s})  "
              f"buffer={ip.buffer_quota_per:.0%}  hsr={ip.hsr_allowed}")

print("\n  --- fallback test ---")
xx = infra.get_or_default("XX")
print(f"  [XX unknown] → {'_default applied' if xx else 'no default found'}")

# --- stop params ---
print("\n=== Stop Params ===")
for stop_id in ["Wien Hbf", "Salzburg Hbf", "München Hbf"]:
    sp = stop_params.get(stop_id)
    if sp:
        print(f"  {sp.stop_id:20s}  {sp.stop_country_code}  "
              f"({sp.lat:.4f}, {sp.lon:.4f})  charge={sp.stop_charge_eur} €")
    else:
        print(f"  {stop_id:20s}  NOT FOUND")

# --- demand ---
print("\n=== Demand ===")
for relation_id, d in demand.all().items():
    print(f"  {relation_id:25s}  {d.origin_stop_id:15s} → {d.destination_stop_id:15s}  "
          f"seat={d.demand_seat_pax:.0f}  couch={d.demand_couchette_pax:.0f}  "
          f"sleep={d.demand_sleeper_pax:.0f}")

#.....
print("\n=== Raw NJ-3.1 cost columns ===")
raw = loader.get("compositions", "NJ-3.1")
for key in ["comp_description", "comp_purchase_loco_eur", "comp_purchase_coach_eur",
            "comp_cleaning_services_eur_day", "comp_shunting_eur_day"]:
    print(f"  {key}: '{raw.get(key, 'NOT FOUND')}'")