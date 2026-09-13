# Station charges — research notes

Josua's working notes from the 2026-09-10 country batch, kept verbatim
(German). They are the *why* behind each `sources/<cc>_station_charges.csv`:
which document, which of several published figures a night train pays, and
where the author was unsure. The register in `01_source_extraction.ipynb`
carries the condensed, per-document version; this file is the trail back to
the documents.

Additions after intake (2026-09-13) are marked as such.

---

Frankreich:
-------------------
- In Frankreich gibt es keine Stationspreise. Statdessen wird der Stationspreis durch die hohen Trassenpreise (vor allem auf den Hochgeschwindigkeitsstrecken) kompensiert.
Unklar ob das die gesamte Wahrheit ist, gerade der lokbespannte Verkehr ist in Bahnhöfen Frankreichs meines Wissens nach sehr teuer, mein Kentnisstand ist aber begrenzt.
Außerdem keine französischkenntnisse, KI hilft nicht weiter.

Italien:
--------------------
- Hier gibt es mehrere Tarife welche je nach Bahnhof zusammengesetzt werden müssen.
- Klassifizierung der Bahnhöfe: https://www.rfi.it/content/dam/rfi/offerta/extra_pmda/Stazioni_passeggeri_Perimetro_relativo_ai_servizi_extra-PMdA_offerti_in_stazione_v1.pdf?utm_source=chatgpt.com
- Tarife: https://www.rfi.it/content/dam/rfi/offerta/sistema-tariffario-2025-2029/extra_pmda/Listino%20Tariffario%20Servizi%20Extra%20PMdA.pdf?utm_source=chatgpt.com

Berechnung

Für einen eigenwirtschaftlichen Fernverkehrs-/Nachtzug (OA LP) habe ich die in der RFI-Tarifliste 2026 ausgewiesenen Bahnhofskomponenten addiert:
Aree di Accoglienza: 1,44 €/Halt
Servizi Igienici: 0,08 €/Halt
IaP: Base 0,31 €, Standard 1,08 €, Top 4,19 €
Assistenza PRM: 8,08 €/Halt, wenn der Bahnhof einem PRM-Kreis F1/F2 zugeordnet ist.

Die Ausstattung jedes Bahnhofs habe ich aus der RFI-Perimeterliste genommen; dort sind insbesondere PRM-Kreis, Wartebereiche, Toiletten und IaP-Kategorie je Bahnhof angegeben.
Beispielsweise ergibt sich für Napoli Centrale aus F1 + Area nicht vorhanden + Toilette vorhanden + IaP Top:
8,08 + 0,08 + 4,19 = 12,35 € netto/Halt. Die RFI-Liste weist Napoli Centrale als F1 und IaP Top aus.
Für Milano Centrale gilt ebenfalls 12,35 € netto/Halt.
Ich habe außerdem 22 % VAT für die Spalten vat_rate_per und charge_incl_vat_eur verwendet. Die 22 % stehen allerdings nicht in den beiden bereitgestellten RFI-PDFs; dieser Wert ist daher eine ergänzende Annahme und nicht aus den Quellen abgeleitet.
Eine Besonderheit ist Stresa: Im bereitgestellten RFI-Dokument ist bei Stresa keine IaP-Kategorie eingetragen, daher habe ich hierfür keine IaP-Gebühr ergänzt.


Österreich:
-----------------------
- Entgeld pro Station nach Kategorien A,B,C,D: https://infrastruktur.oebb.at/de/geschaeftspartner/schienennetz/snnb/snnb-2026/schienennetz-nutzungsbedingungen-2026.pdf
- Verzeichnis der Bahnhöfe mit Kategorisierung: https://data.oebb.at/dam/jcr:7550377b-e3d1-475b-a8e8-25f236311693/2.3.3%20Verzeichnis%20der%20Verkehrsstationen%202026.xlsx
es gibt auch noch Gebühren für Verkaufsfläche, das trifft aber für die privaten Nachtzuganbieter nicht zu, bzw. wahrscheinlich bezahlt RegioJet für seine Ticketautomaten im Wiener Hbf etwas oder so.


Spanien:
------------------------
- Entgeldsätze für verschiedene Kategorien: https://www.boe.es/eli/es/res/2025/11/04/(2)/dof/spa/pdf
- Kategorisierung der Bahnhöfe: https://www.adif.es/documents/20124/49595425/20251212_04_DR_Adif_Relac.IISS_2026_EUS.pdf/d6b3c6bc-7b79-1fa2-da71-3c8bc675613c?t=1766057210682

Der spanische ADIF-Stationscanon wird nach mehreren Faktoren berechnet:

Stationskategorie × Zugtyp × Halttyp + Intensitätsfaktor

Für 2026 veröffentlicht ADIF folgende Grundtarife pro Halt für Larga Distancia:

Stationskategorie	Ziel	Zwischenhalt	Start
1	115,044 €	44,739 €	127,826 €
2	107,064 €	41,636 €	118,961 €
3	95,968 €	37,321 €	106,631 €
4	52,889 €	20,568 €	58,765 €
5	22,821 €	8,875 €	25,357 €

Zusätzlich kommt grundsätzlich ein Intensitätsentgelt von 0,4000 € je ein-/aussteigendem Fahrgast bei Larga-Distancia-Verkehr hinzu.

Die offizielle Formel lautet sinngemäß:

Stationsentgelt = Haltekomponente + Intensitätskomponente

Dabei hängt die Haltekomponente zusätzlich davon ab, ob der Halt Origen (O), Intermedia (I) oder Destino (D) ist.

Was ich für die CSV angesetzt habe

Da unsere station_charges-Datei einen einzigen Preis pro Bahnhof und Halt benötigt, habe ich eine eindeutige, reproduzierbare Definition verwendet:

Larga Distancia + Intermedia (Zwischenhalt)

Damit ergibt sich:

Kategorie 1 → 44,739 € ≈ 44,74 €
Kategorie 2 → 41,636 € ≈ 41,64 €
Kategorie 3 → 37,321 € ≈ 37,32 €
Kategorie 4 → 20,568 € ≈ 20,57 €
Kategorie 5 → 8,875 € ≈ 8,88 €

Der fahrgastabhängige Intensitätsfaktor ist nicht eingerechnet, weil dafür monatliche, stations- und verkehrsspezifische Ein-/Aussteigerzahlen benötigt werden. Ihn einfach pauschal zu schätzen, wäre nicht sachgerecht. Die offizielle ADIF-Formel bestätigt diese Abhängigkeit.


Portugal
--------------------
- Kategorien A,B,C,D in Anexo 7.3.2 https://servicos.infraestruturasdeportugal.pt/sites/default/files/2%C2%AA%20Adenda%20Diretorio%20da%20Rede%202026_signed.pdf

UK
-----------------------
- hier gibt es keine festen Werte, siehe Begründung von ChatGPT. Ich erstelle keine Liste.
Ich habe die britische Tarifstruktur geprüft. Wichtig: Das Vereinigte Königreich funktioniert hier grundlegend anders als Portugal, Österreich oder Spanien.

Für Great Britain (England, Scotland, Wales) gibt es keinen einheitlichen festen Stationspreis pro Halt. Der zentrale regulierte Stationspreis ist der Station Long Term Charge (LTC) von Network Rail/ORR. Er wird als jährlicher Stationsbetrag festgelegt und anschließend auf die nutzenden Betreiber nach deren Anteil an den vehicle departures verteilt.

Wie wird der Stationspreis berechnet?

Der LTC deckt vor allem die langfristigen Kosten für Maintenance, Repair and Renewal (MRR) der Stationsinfrastruktur sowie Station Information and Security Systems (SISS) ab.

Seit PR23 gibt es zwei wesentliche Methoden:

33 Large / Complex Stations: stationsspezifischer LTC auf Basis der prognostizierten effizienten langfristigen MRR-Ausgaben.
Übrige Stationen: Category-Averaged-Methode; die Stationen werden anhand der Nutzung in Kategorien A–F eingeordnet und regionale Kosten auf diese Kategorien verteilt.
Zusätzlich gibt es den Qualifying Expenditure (QX) für laufende Betriebskosten wie Reinigung, Personal, Utilities und leichte Instandhaltung. Dieser ist nicht einfach ein öffentlich verfügbarer fixer €/Halt-Tarif, sondern wird grundsätzlich zwischen Station Facility Owner und den Zugbetreibern bestimmt. Die offiziellen CP7-LTC-Werte wurden von ORR für 2024–2029 festgelegt und werden jährlich entsprechend CPI indexiert.

Beispielsweise beträgt der im ORR-CP7-Dokument ausgewiesene jährliche LTC in 2023/24-Preisen:

London Euston: £7,559,250
Birmingham New Street: £8,248,503
Edinburgh Waverley: £4,057,548
Glasgow Central: £3,726,856
Leeds: £4,975,614
Manchester Piccadilly: £5,121,130
Reading: £4,332,122
Plymouth: £1,020,250
Swindon: £1,019,288
Daher wäre es fachlich falsch, für Großbritannien einfach einen €/stop-Wert wie in Portugal zu erfinden. Für deine Anwendung müsste ein tatsächlicher Halt entweder über die Betreiber-/Vehicle-Departure-Verteilung auf den jährlichen LTC umgelegt werden oder du definierst bewusst einen Modellwert.

Niederlande
------------------
- Bijlage 25: Klassifizierung als halt, basis, plus, mega, kathedraal: https://www.prorail.nl/siteassets/homepage/samenwerken/vervoerders/documenten/2026-netverklaring/netverklaring-2026---definitieve-versie-d.d.-13-december-2024.pdf?utm_source=chatgpt.com
- Seite 120: trenhalteringscode A,B,C nach Zugtyp und dazugehöriger Tarif für halt, basis, plus, mega und kathedraal

Belgien
------------------
- Aufteilung in S,M und L Bahnhöfe, Preise direkt in Liste enthalten https://www.belgiantrain.be/-/media/corporate/services/rrs/docs2026/spsa-fr-a2-2026.ashx?v=e93bbe0c347e45b08cb8fce1fe389826

Schweiz
------------------
- 2 CHF pro Halt wenn in Anhang 2 aufgelistet https://ch.odat.ch/de/cc/742.122.4-20260201-de.html?utm_source=chatgpt.com
- Alle weiteren Stationsleistungen in Trassenpreis integriert

Dänemark
-------------------
- keine Stationspreise, ist in Trassenpreis enthalten

Bulgarien
-------------------
- es gibt keine Stationspreise, nur Preise für Fläche am Bahnhof (für Geschäfte etc.) https://ten-t.rail-infra.bg/bg/392

Rumänien
-----------------
- Anhang 26.a Abschnitt 2.1: 2,45 RON pro Halt https://cfr.ro/files/ddr/EN%202026/NS%202026.pdf

Ukraine
-----------------
- keine Stationsgebühr. Es gibt Einrichtungsgebühren für Bahnhöfe, aber für Reisende bzw. Nutzer der Bahnhofseinrichtungen

Türkei
-------------------
- Einteilung in Stationen Klasse A oder B
- Preisliste https://static.tcdd.gov.tr/webfiles/userfiles/files/sebekebildirimi/2026/ing/63210.pdf
- Klassifizierung der Bahnhöfe https://static.tcdd.gov.tr/webfiles/userfiles/files/sebekebildirimi/2026/ing/3313101.pdf
- Es müssen mehrere Kennzahlen der Bahnhöfe angeschaut werden, um die Klassifizierung zw. A und B durchzuführen.

Ungarn:
--------------------
- Kategorie I bis IV, Zuschlag von 2,45%, https://vpe.kti.hu/halozati-uzletszabalyzat-husz

Polen:
----------------------
- Einordnung in 5 Kategorien: https://www.pkp.pl/images/download/stacje/sierpien2026/Zacznik%20nr%201%20do%20Regulaminu%20RRJ%202025_2026_sierpie.pdf
- Preisliste. Premium-Bahnhöfe haben extra Preis in dieser Liste https://www.pkp.pl/images/download/stacje/2026/Zacznik%20nr%204%20do%20Regulaminu%20RRJ%202025_2026.pdf

Schweden:
--------------------
- keinen extra Stationspreis

Skowakei:
--------------------
- Klassifizierung in A,B,C in Anex 2.3.A https://www.zsr.sk/en/railway-undertaking/infrastructure/network-statement/2026
- Preise in Annex 5.2.B

Tschechien:
--------------------
https://www.spravazeleznic.cz/dopravci/prohlaseni-o-draze?utm_source=chatgpt.com
Tschechien hat einen stationsbezogenen Haltpreis, allerdings mit einer wichtigen Besonderheit: Der Preis ist nicht nur vom Bahnhof abhängig, sondern auch von der Masse des Personenzuges.

Wie berechnet sich der Stationspreis?

Maßgeblich ist das Prohlášení o dráze 2026 / Network Statement 2026 von Správa železnic

, insbesondere Anhang C.

Správa železnic bezeichnet die relevante Komponente als „cena za použití přístupových komunikací pro cestující“. Sie gehört zum Minimum Access Package und ermöglicht den Reisenden den Zugang zum Personenzug.

Die Formel lautet:

Stationspreis = Zₙᵖᵏ × mₚₖ

pro geplantem Halt. Dabei ist:

Zₙᵖᵏ = Tarif der Stationskategorie in CZK/Halt/t
mₚₖ = relevante Masse des Personenzuges in Tonnen
jeder geplante Halt zum Ein- oder Aussteigen wird berücksichtigt.
Die relevante Zugmasse ist die Gesamtmasse des Zuges abzüglich aktiver Triebfahrzeuge ohne Möglichkeit zur Personenbeförderung, auf volle Tonnen aufgerundet.
Stationskategorien und Tarife 2026

Für den Zeitraum 1. Januar bis 12. Dezember 2026 gelten:

Kategorie	Tarif
11	0,08 CZK / Halt / t
12	0,08 CZK / Halt / t
13	0,07 CZK / Halt / t
14	0,04 CZK / Halt / t
15	0,05 CZK / Halt / t
Die Kategorien beziehen sich auf die Ausgestaltung der Fahrgastzugänge. Kategorie 11 bezeichnet beispielsweise Stationen mit niveaugetrenntem Zugang zu allen Bahnsteigen; Kategorie 13 Stationen, bei denen Bahnsteige über Gleisquerungen erreicht werden. Die Zuordnung erfolgt stationsspezifisch. Die aktuelle 2026er Liste weist beispielsweise Praha hlavní nádraží und Praha-Holešovice als Kategorie 11 aus. Brno hlavní nádraží ist Kategorie 12 und Břeclav Kategorie 11. Lichkov ist Kategorie 13. Hradec Králové hl.n. und Hranice na Moravě sind ebenfalls Kategorie 11.
Was bedeutet das für einen Nachtzug?

Anders als bei der Slowakei kann ich also nicht korrekt sagen:

Praha hl.n. = 5,10 € je Halt.

Man braucht zusätzlich die Zugmasse.

Beispiel für einen Nachtzug mit 500 t relevanter Masse:

Praha hl.n., Kategorie 11:
0,08 CZK × 500 t = 40 CZK pro Halt

Beim ECB-Referenzkurs vom 09.09.2026 von 1 EUR = 24,247 CZK wären das rund 1,65 € netto pro Halt.

Bei einem 400-t-Zug wären es dagegen nur 32 CZK bzw. rund 1,32 €.

Wichtig ist außerdem die Abgrenzung: Správa železnic erklärt im Network Statement 2026, dass sie derzeit keinen zusätzlichen Preis für den Zugang über die Schiene zu Service Facilities kalkuliert oder erhebt.

Die oben beschriebene Fahrgastzugangsgebühr ist bereits Bestandteil des Infrastrukturentgelts/Minimum Access Package.

Umsetzung in der CSV

Deshalb habe ich diesmal bewusst keine fiktive Standard-Zugmasse angenommen. Das wäre für eure Anwendung problematisch.

Stattdessen enthält charge_excl_vat_eur den Tarifkoeffizienten je Halt und Tonne und:

basis = per_stop_per_tonne

Beim ECB-Kurs vom 09.09.2026 ergibt sich:

Kategorie 11/12: 0,003299 €/Halt/t
Kategorie 13: 0,002887 €/Halt/t
Kategorie 14: 0,001650 €/Halt/t
Kategorie 15: 0,002062 €/Halt/t

Damit kann eure Anwendung den korrekten Preis einfach berechnen:

station_charge = charge_excl_vat_eur × relevante Zugmasse in t

Die Datei enthält alle 20 tschechischen Bahnhöfe aus stop_seed_catalog.csv und dieselben Spalten wie de_station_charges.csv.

Das note-Feld dokumentiert zusätzlich die Formel und die Bedeutung von mₚₖ. Diese Lösung ist für Tschechien deutlich belastbarer als einen pauschalen Stationspreis für einen angenommenen 400-, 500- oder 600-t-Nachtzug in die Stammdaten zu schreiben.

---

## Frankreich — Nachtrag 2026-09-13 (David)

Es gibt Stationspreise: Gares & Connexions veröffentlicht das *Document de
référence des gares* (DRG). Annexe A1 »Barème tarifaire — Prestation de base
unifiée« ist ein Preis **je abfahrendem Zug** nach Tarifperimeter
(Bahnhofskategorie A/B/C × Region, plus je ein eigener Perimeter für die 20
größten Bahnhöfe, »TGA«), mit zwei Spalten: »Conventionné régional« (TER/
Transilien) und »Autres trains«. Ein Nachtzug ist »Autres trains«. Annexe
A0.1 listet jede Station mit UIC-Nummer und Perimeter. Zuordnung der
Katalogstops über die UIC-Nummer (7-stellige OSM `uic_ref` gegen die
8-stellige »UIC complet«): 96 von 96, kein Widerspruch zwischen UIC und
Name. Quelle: https://www.garesetconnexions.sncf/en/rail-companies/stations-statement
(Annexen 2024, version saisine; 2026 sobald verfügbar).

## Tschechien — Nachtrag 2026-09-13 (David)

Der Tonnenbezug ist kein Transkriptionsproblem, sondern ein Modellproblem:
`CompositionType.total_weight_t()` in `models/params.py` ist genau die
Masse, die Správa železnic mit *mpk* meint (Wagenzug ohne nicht
personenbefördernde Triebfahrzeuge). Die Datei bleibt daher als
`per_stop_per_tonne` in `sources/`, wird aber erst gelesen, wenn das
Kostenmodell sie je Tonne bepreist.
