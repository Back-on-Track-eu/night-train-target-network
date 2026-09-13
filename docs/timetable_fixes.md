# Travel times in the target network tool — what was wrong, what changed

*David → Juri, 2026-09-05. Answer to your Wien–Paris check.*

**In one sentence:** you were right, the times were inflated; the cause was
the per-country time buffer we add on top of the pure running time, not the
route or the speed calculation; it is re-calibrated and Wien–Paris now comes
out at 13:34 instead of 17:21.

---

## 1. What we use

We route on the real rail network (OpenStreetMap data, today's
infrastructure) with a routing engine that knows line speeds and which
trains may use high-speed lines. For each train type it returns the pure
running time at line speed. We then add three things:

1. **acceleration and braking** at every stop, from the train's weight and
   length;
2. **a per-country time buffer** as a percentage of running time — what a
   real timetable needs beyond the theoretical minimum (pathing allowances,
   waiting for faster trains, speed limits the map doesn't know about);
3. **dwell time** at every stop, 2 minutes minimum.

The buffer is the number that was wrong.

## 2. What was wrong, in plain terms

We had calibrated the buffer from the real timetables in the Open Night
Train Database: for every leg of every night train we compared its
scheduled time with our theoretical time and took the average gap per
country. That gave, for example, Austria +35 %, Germany +49 %, France +71 %.

The mistake in content: **a night train's timetable contains two different
kinds of slowness, and we averaged them together.** One is what the network
genuinely needs — a few percent for margin and pathing. The other is the
operator's choice to make the night long enough: nobody wants to arrive in
Paris at 04:00, so the train is given a slow path through the small hours
and stands around. That second kind is huge on the one long overnight leg
of every train, and because that leg is also the longest, it dominated the
average. We were measuring how long operators let trains wait at night and
calling it a property of the country's tracks.

France made it worse: every French night train in the database is an
Intercités de Nuit — domestic, low priority, slow at every hour. Nothing in
the database runs France at Nightjet speed, so France got the biggest
buffer of all, and France is the longest part of Wien–Paris.

Checked against the real NJ 468 (Wien 18:13 → Paris Est 09:38, 15:25 in
the 2024/25 timetable, on the classic line via Strasbourg–Nancy):

| | what our buffer assumed | what the real train needed |
|---|---|---|
| Austria | +35 % | +22 % |
| Germany | +49 % | +58 % (deliberately slow through the night) |
| France | **+71 %** | **+25 %** |

Germany slow, France fast — the shape of the real train is the operator's
night design, not the countries' networks. The routing itself was fine:
1369 km in the tool against 1354 km real, on the same path.

## 3. What changed

The buffer is now calibrated as a **minimum driving time**: per country we
take the *tight* legs of the real timetables (the lower quarter of the
distribution) instead of the average, so the deliberate night waiting is no
longer in it. France is set to 25 % by hand, from the NJ 468 evidence,
because the database cannot give a French value we trust — this is written
down as an exception to be replaced when a French international night train
appears in the data.

| | before | **now** |
|---|---|---|
| Austria | 35 % | **11 %** |
| Germany | 49 % | **19 %** |
| France | 71 % | **25 %** |
| Italy | 54 % | **21 %** |
| Poland | 57 % | **22 %** |
| Sweden | 68 % | **35 %** |

Three technical defects were fixed alongside (Britain's data was being
dropped by a naming mismatch; eight countries incl. Italy and Poland were
silently running on a European default; a scenario setting that no longer
worked with the new numbers). None of them changes the story above.

## 4. What it means for Wien–Paris

Your train: Nightjet next generation, 14 coaches, today's lines, no
high-speed running.

| | before | **now** | real NJ 468 |
|---|---|---|---|
| on the real NJ 468 path | 17:21 | **13:34** | 15:25 (14:46 at launch) |
| your variant via Mannheim with the 90-minute coupling stand | 20:08 | **16:07** | — |

13:34 is the *minimum*: what the corridor needs before deciding when the
train should arrive. The real train was slower because it was deliberately
slowed through Germany to arrive at breakfast — that is a timetable
decision, and it should be one, not a hidden cost.

Two smaller points on your numbers: 1390 km is right (1354 on the classic
path); and "14.5 h" was the press-release figure — the train never ran
faster than 14:46, and ended at 15:25. On the high-speed line Wien–Linz:
that section alone is worth about 20 minutes, not an hour. Our high-speed
scenario gains more because it also puts the train on the LGV Est to Paris,
which the real train never used.

## 5. What you can't do yet in the tool

You cannot yet say "this train should take 15:25" or "add 90 minutes at
Mannheim for the coupling". The tool places every train around the night
automatically and only stretches it to cover the night window. A **manual
override — target arrival time and fixed operational stops — is planned for
one of the next updates.** It will be shown as waiting time, separate from
running time, so the cost model treats it correctly. The 90 minutes in the
table above were added by hand.

## 6. What the inflated times were costing

From the tool's own evaluation of the daily Wien–Paris pair (about 51 M€
per year in total cost at the old buffers):

- Costs that follow **hours** — crew and driver, about 7 M€/yr — fall with
  the 22 % shorter trip: **roughly 1.5–2 M€ per year, 3–4 % of total cost.**
- Costs that follow **kilometres** — maintenance, track access, energy,
  about 21 M€/yr — do not move.
- Costs that follow **fleet size** — financing, depreciation, cleaning,
  overhead, about 17 M€/yr — move in steps. Wien–Paris needs two trainsets
  either way. But any corridor where the shorter trip lets the daily cycle
  drop a set saves that set's share: **roughly 8–9 M€ per year** for a
  train of this size. Several 10–12 hour corridors were close to that line
  with the old buffers.

So the old calibration made every night train in the tool about 20 %
slower than it needs to be, 3–4 % dearer on time alone, with a fleet-size
cliff on top for some corridors — and it did so most on French routes,
where the extra padding was least deserved. The exact figure for any
corridor comes from a single run of the tool after the update.
