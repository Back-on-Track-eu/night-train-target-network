-- 2026-09-21 — VAT on rail passenger tickets, per country (backend 0.5.8)
--
-- A new catalogue table, input_params.ticket_vat_rates, seeded with the
-- rows models/demand/calib/vat/vat_calibration.py produces (its
-- VAT_CALIBRATION.md states the sources). Display only: the frontend shows
-- gross fares beside the net ones; no cost, revenue or subsidy figure
-- changes, so no stored proposal is outdated by this.
--
-- Idempotent: the table is created if absent, the source rows are matched
-- by description, and every rate row is ON CONFLICT DO NOTHING — a database
-- seeded from db/schema.py already carries all of this.

CREATE TABLE IF NOT EXISTS input_params.ticket_vat_rates (
    country_code CHAR(2) PRIMARY KEY REFERENCES input_params.countries(country_code),
    vat_domestic_per NUMERIC(5,3) NOT NULL,
    vat_international_per NUMERIC(5,3) NOT NULL,
    vat_status VARCHAR(20) NOT NULL,
    vat_note TEXT,
    vat_src INTEGER REFERENCES input_params.sources(source_id)
);

COMMENT ON TABLE input_params.ticket_vat_rates IS 'VAT on rail passenger tickets, per country: the rate on a domestic ticket and the rate on the country''s share of a cross-border ticket (0 where the international leg is exempt). Calibrated by models/demand/calib/vat/vat_calibration.py. Display-only: the cost/revenue model prices net.';
COMMENT ON COLUMN input_params.ticket_vat_rates.vat_domestic_per IS 'VAT rate on a ticket that starts and ends in the country, as a fraction (0.070 = 7 %).';
COMMENT ON COLUMN input_params.ticket_vat_rates.vat_international_per IS 'VAT rate on the country''s distance share of a ticket that crosses a border, as a fraction; 0 where the international leg is exempt.';
COMMENT ON COLUMN input_params.ticket_vat_rates.vat_status IS 'Provenance: sourced / assumed / no_railway / blocked — see VAT_CALIBRATION.md.';

-- The source documents, matched by description (the seeder resolves the FK
-- the same way), inserted only where absent.
INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)', 'https://www.transportenvironment.org/articles/european-long-distance-passenger-transport-vat-gap-analysis', '2025-11-20'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)');

INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'European Commission, DG TAXUD / CE Delft (2017): Study on the economic effects of the current VAT rules for passenger transport — international rail taxed in AT, BE, HR, DE, GR, NL, ES', 'https://taxation-customs.ec.europa.eu/document/download/b98dfd42-245a-40f5-b702-2680b68f4026_en', '2017-12-01'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'European Commission, DG TAXUD / CE Delft (2017): Study on the economic effects of the current VAT rules for passenger transport — international rail taxed in AT, BE, HR, DE, GR, NL, ES');

INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025', 'https://ec.europa.eu/taxation_customs/tedb/', '2025-07-01'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025');

INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'Eidgenössische Steuerverwaltung: MWST-Branchen-Info 10, Transportunternehmungen des öffentlichen und des touristischen Verkehrs — Personenbeförderung im Inland (Normalsatz 8,1 %) und grenzüberschreitende Personenbeförderung im Eisenbahnverkehr', 'https://www.estv.admin.ch/estv/de/home/mehrwertsteuer.html', '2024-01-01'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'Eidgenössische Steuerverwaltung: MWST-Branchen-Info 10, Transportunternehmungen des öffentlichen und des touristischen Verkehrs — Personenbeförderung im Inland (Normalsatz 8,1 %) und grenzüberschreitende Personenbeförderung im Eisenbahnverkehr');

INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'HM Revenue & Customs: VAT Notice 744A — passenger transport (zero rate for vehicles, ships and aircraft carrying ten or more passengers; scheduled rail)', 'https://www.gov.uk/guidance/vat-on-passenger-transport-notice-744a', '2024-04-01'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'HM Revenue & Customs: VAT Notice 744A — passenger transport (zero rate for vehicles, ships and aircraft carrying ten or more passengers; scheduled rail)');

INSERT INTO input_params.sources (source_description, source_url, source_date)
SELECT 'Skatteetaten (Norway): merverdiavgift — persontransport 12 %; merverdiavgiftsloven § 6-28, fritak for transport direkte til eller fra utlandet', 'https://www.skatteetaten.no/', '2025-01-01'
WHERE NOT EXISTS (SELECT 1 FROM input_params.sources WHERE source_description = 'Skatteetaten (Norway): merverdiavgift — persontransport 12 %; merverdiavgiftsloven § 6-28, fritak for transport direkte til eller fra utlandet');

INSERT INTO input_params.ticket_vat_rates
    (country_code, vat_domestic_per, vat_international_per, vat_status, vat_note, vat_src)
VALUES
    ('DE', 0.070, 0.070, 'sourced', '7 % on long-distance rail since 2020; Germany taxes the German section of an international ticket',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('AT', 0.100, 0.100, 'sourced', '10 % reduced rate on passenger transport; the Austrian section of an international ticket is taxed (ÖBB invoices) — T&E 2025 no longer lists AT, review',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission, DG TAXUD / CE Delft (2017): Study on the economic effects of the current VAT rules for passenger transport — international rail taxed in AT, BE, HR, DE, GR, NL, ES')),
    ('CH', 0.081, 0.000, 'sourced', 'Normalsatz 8,1 % im Inland; die grenzüberschreitende Eisenbahnbeförderung ist für den inländischen Streckenteil steuerbefreit',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Eidgenössische Steuerverwaltung: MWST-Branchen-Info 10, Transportunternehmungen des öffentlichen und des touristischen Verkehrs — Personenbeförderung im Inland (Normalsatz 8,1 %) und grenzüberschreitende Personenbeförderung im Eisenbahnverkehr')),
    ('FR', 0.100, 0.000, 'sourced', '10 % domestic; international rail exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('BE', 0.060, 0.060, 'sourced', '6 % on passenger transport, also on the Belgian section of an international ticket',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('DK', 0.000, 0.000, 'sourced', 'passenger transport exempt without credit',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('SE', 0.060, 0.000, 'sourced', '6 % domestic; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('BG', 0.200, 0.000, 'assumed', 'standard rate on domestic passenger transport; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('HR', 0.250, 0.250, 'sourced', 'standard rate, also on the Croatian section of an international ticket',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('CY', 0.000, 0.000, 'no_railway', 'no railway',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('CZ', 0.120, 0.000, 'sourced', '12 % reduced rate since the 2024 consolidation; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('EE', 0.240, 0.000, 'assumed', 'standard rate (24 % from July 2025) assumed for domestic rail; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('FI', 0.140, 0.000, 'sourced', 'reduced rate 14 % since 2025 (was 10 %); international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('GR', 0.130, 0.130, 'sourced', '13 % reduced rate, applied to international rail too — no cross-border service runs today',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('HU', 0.270, 0.000, 'assumed', 'standard rate assumed for domestic rail; international exempt (T&E 2025)',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('IE', 0.000, 0.000, 'sourced', 'passenger transport exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('IT', 0.100, 0.000, 'sourced', '10 % domestic; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('LV', 0.120, 0.000, 'sourced', '12 % reduced rate on regular domestic passenger transport; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('LT', 0.090, 0.000, 'sourced', '9 % reduced rate on regular passenger transport; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('LU', 0.030, 0.000, 'sourced', '3 % super-reduced rate; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('MT', 0.000, 0.000, 'no_railway', 'no railway',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('NL', 0.090, 0.090, 'sourced', '9 % reduced rate, also on the Dutch section of an international ticket',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('PL', 0.080, 0.000, 'sourced', '8 % reduced rate; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('PT', 0.060, 0.000, 'sourced', '6 % reduced rate; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('RO', 0.110, 0.000, 'assumed', 'reduced rate 11 % (August 2025 reform) assumed for domestic rail; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('SK', 0.230, 0.000, 'assumed', 'standard rate (23 % from 2025) assumed for domestic rail; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('SI', 0.095, 0.000, 'sourced', '9.5 % reduced rate; international exempt',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('ES', 0.100, 0.100, 'sourced', '10 % reduced rate, also on the Spanish section of an international ticket',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Transport & Environment (2025): European long-distance passenger transport — VAT gap analysis. Contribution to the European Commission''s public consultation on VAT rules for travel and tourism; rail annex (member states taxing international rail)')),
    ('NO', 0.120, 0.000, 'sourced', '12 % on passenger transport; transport directly to or from abroad exempt (§ 6-28)',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Skatteetaten (Norway): merverdiavgift — persontransport 12 %; merverdiavgiftsloven § 6-28, fritak for transport direkte til eller fra utlandet')),
    ('GB', 0.000, 0.000, 'sourced', 'zero-rated: scheduled passenger transport',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'HM Revenue & Customs: VAT Notice 744A — passenger transport (zero rate for vehicles, ships and aircraft carrying ten or more passengers; scheduled rail)')),
    ('BA', 0.170, 0.000, 'assumed', 'single standard rate assumed; international transport exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('RS', 0.100, 0.000, 'assumed', 'reduced rate 10 % on passenger transport assumed; international exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('ME', 0.070, 0.000, 'assumed', 'reduced rate 7 % on passenger transport assumed; international exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('AL', 0.200, 0.000, 'assumed', 'standard rate assumed; international transport exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('UA', 0.200, 0.000, 'assumed', 'standard rate assumed for domestic rail; international passenger transport 0 %',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('TR', 0.100, 0.000, 'assumed', 'reduced rate 10 % on passenger transport assumed; international transport exempt (KDV Kanunu Art. 14)',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('MD', 0.200, 0.000, 'assumed', 'standard rate assumed; international exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('MK', 0.050, 0.000, 'assumed', 'preferential 5 % on passenger transport assumed; international exempt by analogy',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('LI', 0.081, 0.000, 'sourced', 'Swiss VAT law applies in Liechtenstein',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'Eidgenössische Steuerverwaltung: MWST-Branchen-Info 10, Transportunternehmungen des öffentlichen und des touristischen Verkehrs — Personenbeförderung im Inland (Normalsatz 8,1 %) und grenzüberschreitende Personenbeförderung im Eisenbahnverkehr')),
    ('BY', 0.200, 0.000, 'blocked', 'routing never enters Belarus',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025')),
    ('RU', 0.200, 0.000, 'blocked', 'routing never enters Russia',
     (SELECT source_id FROM input_params.sources WHERE source_description = 'European Commission: Taxes in Europe Database (TEDB) — VAT rates applied by the member states to domestic passenger transport, CPA 49.10 rail, as published for 2025'))
ON CONFLICT (country_code) DO NOTHING;
