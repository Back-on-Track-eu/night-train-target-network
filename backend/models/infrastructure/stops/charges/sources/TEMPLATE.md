# Station charge source files — the template

One CSV per country, all with **the same twelve columns**. The reader in
`02_station_charges.ipynb` does not know anything about a country: it reads
every file in this folder the same way. Adding a country is a new file plus one
line in `CHARGE_FILES`, never new parsing code.

`charges/sources/<cc>_station_charges.csv`, lowercase ISO 3166-1 alpha-2.

## Columns

| Column | Required | Description |
|---|---|---|
| `stop_id` | yes | Catalog stop id (`osm:n…`/`osm:w…`/`osm:r…`) from `stop_seed_catalog.csv`. **The join key.** Resolve the printed station name to a catalog stop once, by hand, at transcription time — never at read time |
| `stop_name` | yes | The catalog's `stop_name`, copied. For human review only; the reader ignores it |
| `station_printed` | yes | The station's name **exactly as printed in the document**, so any figure can be found again in the source |
| `country_code` | yes | ISO 3166-1 alpha-2, uppercase |
| `charge_excl_vat_eur` | yes | The charge for **one call by one night train**, **net of VAT**, in EUR, `.` as decimal separator. This is what the cost model prices from. Empty means the country levies no station charge — see below |
| `vat_rate_per` | yes | The VAT rate applying to the charge, as a percentage: `19.0`, not `0.19`. `0.0` where the service is exempt |
| `charge_incl_vat_eur` | yes | The same charge **including VAT**, so both figures are visible side by side and can be compared against whichever the document printed |
| `basis` | yes | What the figure is per. `per_call` unless the tariff genuinely differs; anything else must be explained in `note` |
| `price_basis_year` | yes | The year the published figure applies to, e.g. `2026`. Escalation to 2032 happens later, in the notebook — never here |
| `tariff_class` | no | The country's own category for the station (`Preisklasse 2`, `tipologia A`, …). Explains why two stations differ |
| `source_ref` | yes | `source_id` of the document in `01_source_extraction.ipynb`. Every row must cite one |
| `note` | no | Anything a reader needs: which of several published columns was taken, remarks from the document, why a figure is unusual |

CSV format: **comma-separated, UTF-8, `.` as decimal separator**, no thousands
separator. Convert the document's own conventions (German `;` and `,`) during
transcription — the reader must not have to guess.

## The three money columns

Documents differ: some print net figures, some gross. Rather than converting
one into the other and losing what was printed, the file carries **both, plus
the rate**, so a figure can always be compared against its source without
arithmetic.

Fill in whichever the document prints, then compute the other from the rate.
The reader **checks that the three agree** (net x (1 + rate/100) = gross, to
the cent) and raises if they do not — which is what catches a mistyped digit,
a rate that does not apply, or a gross figure entered in the net column.

The cost model prices from `charge_excl_vat_eur`; the gross column exists to
be read by humans and to make the check possible.

## The rules that make the files comparable

**One charge per stop, for one night train calling once.** Where a document
publishes several figures for a station, pick the one a night train actually
pays and say so in `note`. Germany publishes an SPNV (regional) and an SPFV
(long-distance) share; a night train is long-distance, so `charge_eur` is the
SPFV figure and the SPNV share goes in `note`.

**Only sourced values.** No estimates, no interpolating between the country's
tariff classes for a station the document does not list. A stop with no
defensible figure is left out of the file; it then resolves through the
country or global default, which is honest.

**A country that levies nothing gets a file too**, with `charge_eur` empty and
a `note` recording that the network statement levies no station charge. This
is a tariff fact and must be recorded as one: an absent file cannot be
distinguished from a country nobody has looked at yet.

**Every `stop_id` must exist in the current catalog.** The catalog changes —
the 2026-08 restructure replaced 21 duplicate stops — so the reader raises on
an unknown id rather than skipping the row. A skipped row is a station that
silently reverts to the default.
