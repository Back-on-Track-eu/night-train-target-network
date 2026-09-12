---
title: Where the data comes from
description: Every external source this tool draws on, and what each one is used for.
---

# Where the data comes from

Nothing in this tool is invented. Every number either comes from a named
external source, is derived from one by documented arithmetic, or is an
assumption we say is an assumption. This page lists the sources, document by
document; the [methodology pages](/methodology/track-access) explain how each
was turned into the parameters the model uses.

The source register behind this page was last reviewed end to end on
**11 August 2026**. Tariffs move faster than reviews do, so treat a figure as
current to that date rather than to today.

Links are given exactly as the calibration recorded them, which means a
handful now land on a moved page — infrastructure managers reorganise their
tariff sections between timetable years. The document title and publisher are
the durable part of a citation here; where a link fails, search the publisher's
site for the title.

## The vocabulary we use about a number

The calibration records classify every value they produce. The words are
worth knowing, because they appear throughout this documentation:

| Term           | What it means                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------- |
| **sourced**    | Read from a named document at a named location — a section of a network statement, a row of a price list      |
| **derived**    | Computed from sourced values by arithmetic that is written down                                               |
| **benchmark**  | Taken from a comparable country or a pan-European statistic because the country's own figure is not published |
| **assumed**    | Chosen because no source exists. Always carries a stated low–high band                                        |
| **not levied** | The country genuinely does not charge this. Different from missing                                            |
| **missing**    | Nobody has researched it yet. **Never** silently treated as zero                                              |

That last distinction is enforced, not merely intended: a country without
a calibrated charge is priced without that component rather than being
given an invented median, and the database tests assert that such a column
stays indistinguishable from a number nobody entered.

## The railway itself

**OpenStreetMap**, routed through a self-hosted
[OpenRailRouting](https://github.com/geofabrik/OpenRailRouting) engine — a
rail-aware fork of GraphHopper. This supplies the track geometry, the
distances, and which countries a route passes through. Gauge is respected:
the model routes standard, Iberian, Russian and Irish gauge on separate
profiles, so a train cannot silently cross a break of gauge.

## Existing night trains

The **Open Night Train Database (ONTD)**, a community-maintained record of
services actually running in Europe, compiled by Juri Maier and others at
Back-on-Track. It supplies the existing-route context you see in the gallery,
part of the stop catalogue, and the observed timetable slack used to calibrate
schedule buffers. The model reads it as a database schema rather than as a
document, but the database itself is
[public](https://back-on-track.eu/night-train-database).

## Energy consumption

**[Deutsche Bahn Trassenfinder](https://trassenfinder.de)**, an official tool
that returns the technical energy consumption of a specified train over a
specified route. Querying it across many routes and train configurations
produced the dataset the [energy model](/methodology/energy) is fitted to.
This is a measurement-grade source, and it is the reason energy is one of the
better-founded lines in the model.

## Track access

Every European infrastructure manager is legally required to publish a network
statement setting out what it charges and on what basis. These are the source
for [track access](/methodology/track-access), and they are the best-sourced
part of the model: thirty documents, covering twenty-eight countries plus the
Channel Tunnel.

| Country        | Document                                                                                                                                                                    | Publisher                                              |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Austria        | [Schienennetz-Nutzungsbedingungen 2027](https://infrastruktur.oebb.at/de/geschaeftspartner/schienennetz/snnb/snnb-2027/schienennetz-nutzungsbedingungen-2027.pdf)           | ÖBB-Infrastruktur AG                                   |
| Belgium        | [Network Statement 2027 (version 30 June 2026)](https://infrabel.be/en/networkstatement)                                                                                    | Infrabel                                               |
| Bulgaria       | [Charges and Prices, Annex 5.3.2 v.06](https://www.rail-infra.bg/en/353)                                                                                                    | NRIC (National Railway Infrastructure Company)         |
| Switzerland    | [SR 742.122 Eisenbahn-Netzzugangsverordnung (NZV)](https://www.fedlex.admin.ch/eli/cc/1999/142/de#a21)                                                                      | Swiss Confederation (Fedlex)                           |
|                | [SR 742.122.4 NZV-BAV (BAV ordinance on network access)](https://www.fedlex.admin.ch/eli/cc/2012/371/de)                                                                    | Federal Office of Transport (BAV)                      |
| Channel Tunnel | [Fixed Link Usage Annual Statement 2026, Annexe 4](https://www.getlinkgroup.com/en/our-group/eurotunnel/railway-network/)                                                   | Getlink (Eurotunnel)                                   |
| Czechia        | [Network Statement 2027 (EN web version)](https://www.spravazeleznic.cz/web/en/network-statement-2027)                                                                      | Správa železnic                                        |
| Germany        | [INB 2026 Anlage 5.3 (Redaktionsstand 12 Dec 2025)](https://www.dbinfrago.com/web/schienennetz/leistungen/trassen/trassenpreissystem-2026/schienenpersonenfernverkehr-spfv) | DB InfraGO AG                                          |
| Denmark        | Bekendtgørelse om infrastrukturafgifter m.v. (BEK 2024/1351) (no public link)                                                                                               | Danish Transport Ministry / Banedanmark                |
| Estonia        | [Raudteeinfrastruktuuri kasutustasu määrad (published rate table)](https://ttja.ee/ariklient/raudtee/kasutustasu-maarad)                                                    | Tarbijakaitse ja Tehnilise Järelevalve Amet (TTJA)     |
| Spain          | [BOE-A-2024-22140 (consolidated) — railway charges](https://www.boe.es/buscar/act.php?id=BOE-A-2024-22140)                                                                  | Boletín Oficial del Estado                             |
| Finland        | [Verkkoselostus / Network Statement 2027](https://www.doria.fi/bitstream/handle/10024/195216/vj_2026-38eng_978-952-405-425-6.pdf?sequence=1&isAllowed=y)                    | Väylävirasto (Finnish Transport Infrastructure Agency) |
| France         | [DRR 2027 Appendix 5.2 — scale of minimum services](https://www.sncf-reseau.com/en/drr/network-statement-national-rail-network-timetable-2027)                              | SNCF Réseau                                            |
| Greece         | [Network Statement 2026 (EN final)](https://ose.gr/wp-content/uploads/2026/02/OSE_2026-ENG_Final.pdf)                                                                       | OSE                                                    |
| Croatia        | [Izvješće o mreži / Network Statement 2027](https://eng.hzinfra.hr/?page_id=284)                                                                                            | HŽ Infrastruktura                                      |
| Hungary        | [Network Statement 2026-2027, Annex 5.2-6](https://vpe.kti.hu/en/network-statement/network-statement-2026-2027/)                                                            | VPE / MÁV                                              |
| Ireland        | [Network Statement 2027](https://www.irishrail.ie/en-ie/about-us/iarnrod-eireann-network-statement)                                                                         | Iarnród Éireann                                        |
| Italy          | [Listino Tariffario Pacchetto Minimo di Accesso (PMdA)](https://www.rfi.it/en/railway-infrastructure-access-/Network-statement.html)                                        | RFI                                                    |
| Lithuania      | [Network Statement 2026-2027 and annexes v1](https://ltginfra.lt/en/railway-infrastructure/map/network-statements/)                                                         | LTG Infra                                              |
| Luxembourg     | [Document de référence du réseau 2027 (EN v1.0)](https://acf.gouvernement.lu/en/sillon/Document-de-reference-du-reseau.html)                                                | ACF / CFL                                              |
| Latvia         | [Network Statement 2027](https://www.ldz.lv/en/network-statement-2027)                                                                                                      | LDz / LatRailNet                                       |
| Netherlands    | [Network Statement 2027 (version 1.1, 6 May 2026)](https://www.prorail.nl/samenwerken/vervoerders/network-statement)                                                        | ProRail                                                |
| Norway         | [Network Statement 2027 (EN v1.1)](https://oppslagsverk.banenor.no/en/network-statement/)                                                                                   | Bane NOR                                               |
| Poland         | [Network Statement 2026/2027 Annex 9.1 (SMK)](https://en.plk-sa.pl/for-customers-and-partners/the-rules-for-allocating-train-paths/network-statement-2026/2027)             | PKP Polskie Linie Kolejowe                             |
| Portugal       | [1st Addenda to Network Statement 2027](https://servicos.infraestruturasdeportugal.pt/sites/default/files/1st%20Addenda%20Network%20Statement%202027_0.pdf)                 | Infraestruturas de Portugal                            |
| Romania        | [Network Statement Annex 25.a](https://cfr.ro/download-drr-2026-network-statement/)                                                                                         | CFR SA                                                 |
| Sweden         | [Network Statement 2027, Annex 1B](https://bransch.trafikverket.se/en/startpage/operations/Operations-railway/Network-Statement/network-statement-2027/)                    | Trafikverket                                           |
| Slovenia       | [Program omrežja / Network Statement 2027](https://infrastruktura.sz.si/en/partners/access-to-infrastructure-for-rus/network-statement/)                                    | SŽ-Infrastruktura                                      |
| Slovakia       | [Network Statement 2027 Annex 5.2.B (Measure 2/2018)](https://www.zsr.sk/en/railway-undertaking/infrastructure/network-statement/network-statement-2027/)                   | ŽSR                                                    |
| United Kingdom | [CP7 Track Usage Price List](https://www.networkrail.co.uk/industry-and-commercial/information-for-operators/network-statement/)                                            | Network Rail                                           |

Cross-check, conversion and method sources. These price no country on their own; they underpin the exchange-rate table, the escalation to 2032 prices and the decisions about what a night train actually pays.

| Document                                                                                                                                                                                                                              | Publisher                                          |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [Schienennetz-Nutzungsbedingungen 2026](https://infrastruktur.oebb.at/de/geschaeftspartner/schienennetz/snnb)                                                                                                                         | ÖBB-Infrastruktur AG                               |
| [BK10-25-0067 Anlage 2 — approved consolidated INB 2026](https://www.bundesnetzagentur.de/DE/Beschlusskammern/1_GZ/BK10-GZ/2025/2025_0001bis0099/BK10-25-0067/Anlagen/BK10-25-0067_Z_Anlage2_Download.pdf?__blob=publicationFile&v=2) | Bundesnetzagentur                                  |
| [Declaración sobre la Red 2027 (NS ADIF V1)](https://www.adif.es/sobre-adif/declaracion-red)                                                                                                                                          | Adif / Adif Alta Velocidad                         |
| [DRR 2027 Annexe 5.1.2](https://www.sncf-reseau.com/en/drr/network-statement-national-rail-network-timetable-2027)                                                                                                                    | SNCF Réseau                                        |
| [Network Statement 2027 (June 2026)](https://www.rfi.it/en/railway-infrastructure-access-/Network-statement.html)                                                                                                                     | RFI                                                |
| [IRG-Rail Track Access Charges survey 2025 (updated)](https://irg-rail.eu/irg/documents/track-access-charges-summary)                                                                                                                 | IRG-Rail                                           |
| [IRG-Rail 14th Annual Market Monitoring Report (main report and dataset)](https://irg-rail.eu/irg/documents/market-monitoring)                                                                                                        | IRG-Rail                                           |
| [IRG-Rail 9th Annual Market Monitoring Report](https://irg-rail.eu/irg/documents/market-monitoring)                                                                                                                                   | IRG-Rail                                           |
| [Overview of Charging Practices for the Minimum Access Package in Europe](https://irg-rail.eu/irg/documents/track-access-charges-summary)                                                                                             | IRG-Rail                                           |
| [ECB euro foreign exchange reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)                                                                               | European Central Bank                              |
| [Eurosystem staff macroeconomic projections for the euro area](https://www.ecb.europa.eu/press/projections/html/index.en.html)                                                                                                        | European Central Bank                              |
| [Eisenbahnregulierungsgesetz §37 and ECJ ruling C-770/24 on the Trassenpreisbremse](https://curia.europa.eu/juris/liste.jsf?num=C-770/24)                                                                                             | Bundestag / Court of Justice of the European Union |

## Traction electricity

What the operator pays for the electricity itself, as distinct from the path.
Some of this comes out of the same network statements; the rest comes from
supply tariffs and from European statistics where no rail-specific price is
published. See [traction electricity](/methodology/energy-pricing).

| Country     | Document                                                                                                                                                        | Publisher                                              |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Austria     | [Schienennetz-Nutzungsbedingungen 2026](https://infrastruktur.oebb.at/de/geschaeftspartner/schienennetz/snnb)                                                   | ÖBB-Infrastruktur AG                                   |
| Belgium     | [Network Statement 2027 (version 30 June 2026)](https://infrabel.be/en/networkstatement)                                                                        | Infrabel                                               |
| Switzerland | [SR 742.122 Eisenbahn-Netzzugangsverordnung (NZV)](https://www.fedlex.admin.ch/eli/cc/1999/142/de#a21)                                                          | Swiss Confederation (Fedlex)                           |
| Germany     | [Anlagenpreissystem 2027 — Entgelte für Serviceeinrichtungen](https://www.dbinfrago.com/web/schienennetz/regelwerke-nutzungsbedingungen/preise)                 | DB InfraGO                                             |
|             | [Preisblatt Netznutzung Bahnstromnetz, from 01.01.2026](https://www.dbenergie.de/dbenergie-de/Produkte/bahnstrom)                                               | DB Energie                                             |
| Finland     | [Verkkoselostus / Network Statement 2027](https://www.doria.fi/bitstream/handle/10024/195216/vj_2026-38eng_978-952-405-425-6.pdf?sequence=1&isAllowed=y)        | Väylävirasto (Finnish Transport Infrastructure Agency) |
| France      | [DRR 2027 Appendix 5.2 — scale of minimum services](https://www.sncf-reseau.com/en/drr/network-statement-national-rail-network-timetable-2027)                  | SNCF Réseau                                            |
|             | [DRR 2027 Annexe 5.1.2 — tarification de la traction électrique](https://www.sncf-reseau.com/en/drr/network-statement-national-rail-network-timetable-2027)     | SNCF Réseau                                            |
| Greece      | [Network Statement 2026 (EN final)](https://ose.gr/wp-content/uploads/2026/02/OSE_2026-ENG_Final.pdf)                                                           | OSE                                                    |
| Croatia     | [Izvješće o mreži / Network Statement 2027](https://eng.hzinfra.hr/?page_id=284)                                                                                | HŽ Infrastruktura                                      |
| Hungary     | [Network Statement 2026-2027, Annex 5.2-6](https://vpe.kti.hu/en/network-statement/network-statement-2026-2027/)                                                | VPE / MÁV                                              |
| Italy       | [Listino Tariffario Pacchetto Minimo di Accesso (PMdA)](https://www.rfi.it/en/railway-infrastructure-access-/Network-statement.html)                            | RFI                                                    |
| Lithuania   | [Network Statement 2026-2027 and annexes v1](https://ltginfra.lt/en/railway-infrastructure/map/network-statements/)                                             | LTG Infra                                              |
| Luxembourg  | [Document de référence du réseau 2027 (EN v1.0)](https://acf.gouvernement.lu/en/sillon/Document-de-reference-du-reseau.html)                                    | ACF / CFL                                              |
| Latvia      | [Network Statement 2027](https://www.ldz.lv/en/network-statement-2027)                                                                                          | LDz / LatRailNet                                       |
| Poland      | [Network Statement 2026/2027 Annex 9.1 (SMK)](https://en.plk-sa.pl/for-customers-and-partners/the-rules-for-allocating-train-paths/network-statement-2026/2027) | PKP Polskie Linie Kolejowe                             |
| Romania     | [Network Statement Annex 25.a / 26.a](https://cfr.ro/download-drr-2026-network-statement/)                                                                      | CFR SA                                                 |
| Sweden      | [Network Statement 2027, §7.3.11](https://bransch.trafikverket.se/en/startpage/operations/Operations-railway/Network-Statement/network-statement-2027/)         | Trafikverket                                           |
| Slovakia    | [Network Statement 2027 Annex 5.2.B (Measure 2/2018)](https://www.zsr.sk/en/railway-undertaking/infrastructure/network-statement/network-statement-2027/)       | ŽSR                                                    |

Statistics, tax treatment and escalation. These do not price one country; they underpin the benchmark, the tax reconciliation and the conversion to 2032 prices.

| Document                                                                                                                                                                                 | Publisher                                   |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| [EU-Vergleich Besteuerung von Eisenbahn-Fahrstrom](https://www.allianz-pro-schiene.de/themen/umwelt/energieverbrauch/)                                                                   | Allianz pro Schiene                         |
| [Transport taxes and charges in Europe (4.K83) and accompanying database](https://cedelft.eu/publications/transport-taxes-and-charges-in-europe/)                                        | CE Delft for the European Commission        |
| [Prices of fuels purchased by non-domestic consumers, Tables 3.4.1 and 3.4.2](https://www.gov.uk/government/statistical-data-sets/gas-and-electricity-prices-in-the-non-domestic-sector) | Department for Energy Security and Net Zero |
| [Electricity price components for non-household consumers (nrg_pc_205_c)](https://ec.europa.eu/eurostat/databrowser/view/nrg_pc_205_c/default/table)                                     | Eurostat                                    |
| [Services exempt from VAT](https://skat.dk/en-us/businesses/vat/services-exempt-from-vat)                                                                                                | Skattestyrelsen (Danish Tax Agency)         |

## Shunting, stabling and station charges

Shunting movements, overnight stabling and the per-call station fee. This is
the weakest-sourced of the charge domains: seventeen of twenty-eight countries
fall back on a European default rather than a national figure, and the market
top-up added on top of the published charge is larger than many of the charges
it sits on. See [shunting and stabling](/methodology/facility).

| Country  | Document                                                                                                                                                        | Publisher                                      |
| -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Austria  | [Schienennetz-Nutzungsbedingungen 2026](https://infrastruktur.oebb.at/de/geschaeftspartner/schienennetz/snnb)                                                   | ÖBB-Infrastruktur AG                           |
| Belgium  | [Network Statement 2027 (version 30 June 2026)](https://infrabel.be/en/networkstatement)                                                                        | Infrabel                                       |
| Bulgaria | [Charges and Prices, Annex 5.3.2 v.06](https://www.rail-infra.bg/en/353)                                                                                        | NRIC (National Railway Infrastructure Company) |
| Germany  | [Anlagenpreissystem 2027 — Entgelte für Serviceeinrichtungen](https://www.dbinfrago.com/web/schienennetz/regelwerke-nutzungsbedingungen/preise)                 | DB InfraGO                                     |
| Denmark  | [Network Statement 2027](https://www.bane.dk/en/Railway/Network-Statement)                                                                                      | Banedanmark                                    |
| Spain    | [Declaración sobre la Red 2027 (NS ADIF V1)](https://www.adif.es/sobre-adif/declaracion-red)                                                                    | Adif / Adif Alta Velocidad                     |
| Greece   | [Network Statement 2026 (EN final)](https://ose.gr/wp-content/uploads/2026/02/OSE_2026-ENG_Final.pdf)                                                           | OSE                                            |
| Croatia  | [Izvješće o mreži / Network Statement 2027](https://eng.hzinfra.hr/?page_id=284)                                                                                | HŽ Infrastruktura                              |
| Hungary  | [Network Statement 2026-2027, Annex 5.2-6](https://vpe.kti.hu/en/network-statement/network-statement-2026-2027/)                                                | VPE / MÁV                                      |
| Italy    | [Network Statement 2027](https://www.rfi.it/en/railway-infrastructure-access-/Network-statement.html)                                                           | RFI                                            |
| Norway   | [Network Statement 2027 (EN v1.1)](https://oppslagsverk.banenor.no/en/network-statement/)                                                                       | Bane NOR                                       |
| Poland   | [Network Statement 2026/2027 Annex 9.1 (SMK)](https://en.plk-sa.pl/for-customers-and-partners/the-rules-for-allocating-train-paths/network-statement-2026/2027) | PKP Polskie Linie Kolejowe                     |
| Portugal | [1st Addenda to Network Statement 2027](https://servicos.infraestruturasdeportugal.pt/sites/default/files/1st%20Addenda%20Network%20Statement%202027_0.pdf)     | Infraestruturas de Portugal                    |
| Slovenia | [Program omrežja / Network Statement 2027](https://infrastruktura.sz.si/en/partners/access-to-infrastructure-for-rus/network-statement/)                        | SŽ-Infrastruktura                              |

Cross-check and method sources. These underpin the market top-up and the per-country labour index, not any published tariff.

| Document                                                                              | Publisher                          |
| ------------------------------------------------------------------------------------- | ---------------------------------- |
| Night train business case model, 2030 scenario (no public link)                       | Nox Mobility (publisher TO_VERIFY) |
| [Nachtzugstudie — Wirtschaftlichkeit von Nachtzugverbindungen](https://bmdv.bund.de/) | Ramboll for BMDV                   |

Station charges are separate again, and thinner still. Germany's
**Stationspreisliste 2026** (DB InfraGO AG) is transcribed in full, covering
all 5,412 German stations. Seventeen countries have no transcribed price list
at all — see [station charges](/cost/station-charge).

Bulgaria's annex does double duty here: it is both Bulgaria's own stabling
rate and the European default rate the seventeen unsourced countries fall back
on. Read a default country's figure as "the European average, tier-adjusted",
not as a national tariff.

## Terrain and buffers

How much slack a country's timetabling practice carries, and how much a
route's terrain slows a train. No infrastructure manager publishes either, so
this domain has no per-country tariff document behind it — the figures come
from observed timetables and from pan-European statistics. See
[terrain and buffers](/methodology/route-context).

| Document                                                                                                                                                | Publisher                                     |
| ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| [Ninth report on monitoring development of the rail market (RMMS), COM(2024)](https://transport.ec.europa.eu/transport-modes/rail/market-monitoring_en) | European Commission (DG MOVE)                 |
| [UIC Leaflet 451-1: Timetable recovery margins to guarantee timekeeping](https://uic.org/)                                                              | International Union of Railways               |
| [Open Night Train Database — observed trip timings](https://back-on-track.eu/night-train-database)                                                      | Back-on-Track                                 |
| Corridor-by-corridor topographic assessment of the target network (no public link)                                                                      | Back-on-Track EU, internal to this repository |

## Rolling stock and operating costs

Coach and locomotive prices, crew pay, maintenance and overhead. There is no
equivalent of a network statement here: vehicle prices are commercial, so the
calibration reads them out of annual reports, procurement awards and trade
press, and triangulates.

Read this list differently from the ones above. It contains audited accounts
and public procurement records, but also salary aggregators and press
reporting of contract values. The calibration records a reliability note per
document for exactly this reason. See
[rolling stock](/methodology/compositions).

**Studies and methodology**

| Document                                                                                                                                                                                                                                             | Publisher                                               | Year |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- | ---- |
| [UIC Study Night Trains 2.0. New opportunities by HSR?](https://shop.uic.org/en/other-reports/1249-uic-study-night-trains-2-0-final-presentation-new-opportunities-by-hsr-executive-summary.html)                                                    | DB International GmbH for UIC                           | 2013 |
| Nachtzugstudie BMDV — Präsentation Ergebnisse (no public link)                                                                                                                                                                                       | BMDV / consortium                                       | 2025 |
| [Studie Bilanz von Nachtzugverkehren](https://www.bmv.de/SharedDocs/DE/Publikationen/E/studie-bilanz-nachtzugverkehre.html)                                                                                                                          | Ramboll for BMV                                         | 2025 |
| [Machbarkeitsuntersuchung: Berlin als Drehkreuz eines europäischen Nachtzugnetzes](https://www.berlin.de/sen/uvk/_assets/verkehr/verkehrsplanung/eisenbahnverkehr/planungen/berlin-als-drehkreuz-eines-europaeischen-nachtzugnetzes.pdf)             | Ramboll for SenUMVK Berlin                              | 2023 |
| [Long-distance cross-border passenger rail services](https://op.europa.eu/en/publication-detail/-/publication/34244751-6ea3-11ec-9136-01aa75ed71a1)                                                                                                  | Steer & KCW for European Commission DG MOVE             | 2021 |
| [Potentialabschätzung von Nachtzügen in Europa (Masterarbeit)](https://bildungsservice.org/fileadmin/user_upload/DIYII/Angebote/Abschlussarbeiten/Abschlussarbeiten/2025_Janne_Schoenerstedt_Masterarbeit_d.pdf)                                     | Janne Schönerstedt                                      | 2025 |
| [Aktualisierung der Kosten- und Wertansätze der Bundesverkehrswegeplanung (FE VB970452, Schlussbericht Dez 2024)](https://www.bmv.de/SharedDocs/DE/Anlage/G/aktualisierung-kosten-wertansaetze-bundesverkehrswegeplanung.pdf?__blob=publicationFile) | TTS TRIMODE / Intraplan / Planco / SSP Consult for BMDV | 2024 |
| Back on Track Base Night Train Model (no public link)                                                                                                                                                                                                | Back-on-Track Europe                                    | 2025 |

**Vehicle prices, orders and procurement**

| Document                                                                                                                                                                                                                | Publisher                                  | Year |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ---- |
| [Norske tog FLIRT Nordic Express, 17 × 8-car, NOK 8bn (2023)](https://www.norsketog.no/en/projects/new-long-distance-trains)                                                                                            | Norske tog / Stadler                       | 2023 |
| [Caledonian Sleeper Mk5, 75 cars, £150M (2015)](https://www.railjournal.com/rolling-stock/first-caf-caledonian-sleeper-coaches-arrive-in-britain/)                                                                      | Serco / CAF via press                      | 2015 |
| [Trenitalia Intercity Notte framework ≤370 cars €732.5M; first call 70 cars / €138.59M (2023)](https://www.skodagroup.com/press-release/skoda-group-and-titagarh-firema-won-tender-for-coaches-for-italian-night-lines) | Trenitalia / Škoda Group / Titagarh Firema | 2023 |
| [Trafikverket night train procurement (2025 failed round; 2026 Talgo award; SJ refit)](https://www.trafikverket.se/resa-och-trafik/jarnvag/sveriges-nya-nattag/)                                                        | Trafikverket / Talgo / Siemens             | 2026 |
| ČD loco tender figures (2021 lease framework; 2026 dual-mode bid; ComfortJet) (no public link)                                                                                                                          | ČD / Siemens via zdopravy.cz               | 2026 |
| [DB Gebrauchtzug channel evidence (Bieterverfahren; 73 multi-voltage coaches offered)](https://www.db-gebrauchtzug.de)                                                                                                  | DB Regio                                   | 2026 |
| [ÖBB introduces Siemens Nightjet fleet (Matthä interview)](https://www.railwaygazette.com/passenger/%C3%B6bb-introduces-siemens-nightjet-fleet-as-paris-berlin-sleeper-train-revived/65521.article)                     | Railway Gazette International              | 2023 |
| [ÖBB Orders 20 Additional Nightjets (ÖBB statement on contract volume)](https://www.railvolution.net/news/obb-orders-20-additional-nightjets)                                                                           | Railvolution                               | 2021 |
| [ÖBB 2016 acquisition of DB City Night Line fleet (42 WLABmz sleepers + 15 couchette cars for EUR 40M)](https://www.railjournal.com/passenger/main-line/bb-and-db-finalise-german-overnight-services/)                  | press reports (secondary)                  | 2016 |

**Operator accounts and disclosures**

| Document                                                                                                                                                                                            | Publisher                            | Year      |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | --------- |
| [ELL GmbH & Co. KG Jahresabschluss 2021](https://www.bundesanzeiger.de)                                                                                                                             | Bundesanzeiger                       | 2022      |
| [RDC Deutschland Jahresabschluss 2021](https://www.bundesanzeiger.de)                                                                                                                               | Bundesanzeiger                       | 2022      |
| [Italo S.p.A. Annual Report 2019 (EN)](https://italospa.italotreno.it/static/upload/fin/financial-statement-2019.pdf)                                                                               | Italo / NTV                          | 2020      |
| Valuation European Sleeper — Q1 2026 (no public link)                                                                                                                                               | European Sleeper / valuation advisor | 2026      |
| [European Sleeper Sharefunding 2026 pitch deck](https://storage.googleapis.com/eyevestor2-dev/6psvratjr74_20260109T10373.pdf)                                                                       | European Sleeper                     | 2026      |
| [ÖBB annual report 2025](https://bericht.oebb.at/dam/jcr:b853d6d8-fc1e-408f-a3c4-f9c77bf59d4a/oebb-annual-report-2025.pdf)                                                                          | ÖBB Holding AG                       | 2026      |
| [SNCF Groupe: Au cœur de la production d'un train de nuit (Intercités de nuit fleet renovation figures)](https://www.groupe-sncf.com/fr/groupe/coulisses/metiers-inattendus/production-trains-nuit) | SNCF Groupe                          | 2023      |
| [Trafikverket night train procurement Sweden (TRV 2020/81418)](https://www.railwaygazette.com/passenger/trafikverket-proposes-malm%C3%B6-brussels-overnight-service/56392.article)                  | Trafikverket                         | 2020-2022 |
| Intercités de nuit (TET) cost audits / ART reports France (no public link)                                                                                                                          | ART / Cour des comptes / DGITM       | —         |
| Italo/NTV 2022–23 figures via financial press (no public link)                                                                                                                                      | press                                | 2024      |

**Crew pay**

| Document                                                                                                                                                                     | Publisher              | Year |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ---- |
| [DB–EVG Tarifabschluss 2023 (flat-rate steps)](https://www.evg-online.org/presse/pressemitteilungen/pressemitteilung/tarifrunde-2023-abgeschlossen-11-fakten-zum-abschluss/) | DB/EVG via press       | 2023 |
| [DB-Tarifrunde 2025 (percentage steps)](https://www.evg-online.org/unsere-themen/dein-geld/db-tarifrunde-2025/)                                                              | DB/EVG via press       | 2025 |
| SJ AB official pay scale (Seko agreement) (no public link)                                                                                                                   | SJ / Seko              | 2025 |
| [ÖBB careers pages (driver)](https://karriere.oebb.at)                                                                                                                       | ÖBB                    | 2026 |
| [ÖBB Karriere Zugbegleiter:in](https://karriere.oebb.at)                                                                                                                     | ÖBB                    | 2026 |
| France driver salary aggregators (no public link)                                                                                                                            | aggregators (multiple) | 2026 |
| Italy driver salary aggregators (no public link)                                                                                                                             | aggregators (multiple) | 2026 |
| France chef de bord aggregators (no public link)                                                                                                                             | aggregators (multiple) | 2026 |
| Italy capotreno aggregators (no public link)                                                                                                                                 | aggregators (multiple) | 2026 |

**Escalation and route geometry**

| Document                                                                                                                                                                                 | Publisher             | Year |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ---- |
| [Eurosystem staff macroeconomic projections for the euro area, December 2025](https://www.ecb.europa.eu/press/projections/html/ecb.projections202512_eurosystemstaff~12ead61977.en.html) | European Central Bank | 2025 |
| [BoT Open Night Train Database — route geometry sample](https://back-on-track.eu/night-train-database)                                                                                   | Back-on-Track Europe  | 2026 |

## Country borders

**Marine Regions EEZ land union v4** (Flanders Marine Institute, 2024,
[DOI 10.14284/698](https://doi.org/10.14284/698), CC-BY 4.0). Ordinary
land borders are not enough for a rail network that crosses belts, straits
and tunnels: a train on the Fehmarn crossing or under the Channel is
somewhere, and that somewhere charges for it. Using maritime zones as well
as land means those segments are attributed to a country rather than
falling into an "unknown" bucket.

## Emissions

Per-mode emission factors, recorded in the model as **EEA TERM 2020** and read
as EU-average 2018 figures per passenger-kilometre. The mode-shift assumptions
layered on top of them are ours, not the EEA's — see [emissions](/emissions).

| Document                                                                                                                                                                   | Publisher                   |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| [Transport and environment report 2020 — "Train or plane?" (EEA Report 19/2020)](https://www.eea.europa.eu/en/analysis/publications/transport-and-environment-report-2020) | European Environment Agency |

## One thing that happens exactly once

**Currency conversion and price escalation.** Sources are published in
different currencies and different years. Both conversions happen once, in
the calibration notebooks, at a pinned exchange-rate snapshot and with a
stated escalation to the 2032 evaluation year. From that point on every
number in the database is plain euros at 2032 prices — no calculation
module and no seeding script ever sees a currency or a conversion.

This is why you will not find an exchange rate anywhere in the model, and
why a figure here cannot silently drift with the euro.

## Values with no source

Two entries in the register are placeholders rather than documents, and every
number still pointing at them is an internal estimate, not a published figure:

| Entry                                                              | What still uses it                                                                                                                                                                    |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `B-o-T_targetnetwork_DB_v2.xlsx` — illustrative placeholder values | the original spreadsheet import, now largely superseded                                                                                                                               |
| Illustrative / internal estimate                                   | the eleven countries outside the calibrated set (Albania, Bosnia, Cyprus, Liechtenstein, Malta, Moldova, Montenegro, North Macedonia, Serbia, Türkiye, Ukraine), and stop coordinates |

Fourteen further entries are real sources cited without a public link,
because they are not published, are commercially confidential, or the link was
never recorded: the Danish charging order BEK 2024/1351, the Back-on-Track base
night train model, the BMDV Nachtzugstudie presentation, the French TET cost
audits, the Nox Mobility business case model, the European Sleeper valuation,
the ČD locomotive tender figures, Italo's figures via the financial press, SJ's
pay scale, the four national salary aggregator sets behind crew pay, and the
internal corridor topography assessment. Each is listed above in its own
section marked "no public link" rather than omitted, so the gap is visible
rather than tidy.

## A caution about country figures

A number attached to a country is not automatically that country's own
published tariff. In the facility and route-context domains especially, it
is frequently a European average adjusted for the country's tier, because
no national figure is published. The
[methodology pages](/methodology/facility) say which is which, per domain.

<FeedbackForm />
