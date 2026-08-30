import numpy as np, pandas as pd, statsmodels.api as sm

d = pd.read_csv("data/samples_speed.csv")
d["seg"] = d.route_name.astype(str) + "__" + d.start_ds100.astype(str) + "__" + d.end_ds100.astype(str)
d["v"] = d.distance_km / (d.travel_time_min / 60)
keys = ["seg", "composition_id", "stratum"]

# keep only route-stable groups: within these, everything but speed is fixed
stab = d.groupby(keys)["distance_km"].agg(["min", "max"])
ok = stab.index[(stab["max"] - stab["min"]) / stab["min"] < 0.005]
d = d[d.set_index(keys).index.isin(set(ok))]

# sweep the exponent; within-group demeaning removes every constant term
best = []
for p in np.arange(1.5, 3.01, 0.05):
    x = d.weight_t * d.distance_km * d.v**p
    g = d.groupby(keys)
    y = d.energy_traktion_kwh - g.energy_traktion_kwh.transform("mean")
    xg = x.groupby([d[k] for k in keys]).transform("mean")
    xd = x - xg
    best.append((p, sm.OLS(y, xd.to_frame("x")).fit().rsquared))

res = pd.DataFrame(best, columns=["exponent", "within_R2"])
peak = res.loc[res.within_R2.idxmax()]
print(res.iloc[::4].round(4).to_string(index=False))
print(f"\nbest-fitting exponent: {peak.exponent:.2f}   within-group R^2 {peak.within_R2:.5f}")
print("Near 2.0 means the v^2 drag law holds over the observed range, and")
print("applying it above that range is physics rather than curve-fitting.")
