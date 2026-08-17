# Stops and Stop Charges — Reserved

Not yet implemented. Reserved for the per-stop/station charge calibration
(distinct from the CH Haltezuschlag per-stop TAC term already modelled in
`../tac/` — that's a track-access capacity charge, not a station usage
fee). Follows the same contract as the other domains once populated:

```
stops/
├── 07_stops_calibration.ipynb   (numbering continues from 06)
├── STOPS_MODEL.md                per-country/per-station narrative
└── data/                         committed observations + provenance
```

See `../README.md` for the shared contract (stdlib-only compute cells,
`SV`-style provenance, `06`-style seed export) this domain will follow.
