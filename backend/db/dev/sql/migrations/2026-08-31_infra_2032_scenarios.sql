-- =============================================================================
-- Infra 2032 scenarios — the 2026 operating conditions on the upgraded network
-- =============================================================================
-- Adds versions 5, 6 and 7 to all five versioned input_params tables, and the
-- three scenario.scenarios rows that pin them. Mirrors db/dev/seed.py, which
-- is authoritative for local databases; this file is how server databases
-- (staging, production) reach the same state, since they are never reseeded.
--
-- The version grid, per seed.py:
--
--                  baseline   + NT on HSR   + NT on HSR + opt. timetables
--    infra_2026        1            2                   3
--    infra_2032        5            6                   7
--
-- so every new version is its 2026 counterpart + 4. The 2032 snapshots are
-- exact copies: what makes a 2032 scenario different is the routing graph it
-- pins, because an upgraded network is new track and track lives in the
-- routing graph, not in these tables.
--
-- Copies are made with INSERT ... SELECT against the SERVER's own versions
-- 1-3 rather than from literals, so a database whose calibration has moved
-- on since this file was written carries its own values forward. The column
-- list is read from information_schema at run time for the same reason: a
-- column added by a later migration is copied without this file knowing
-- about it. Both the surrogate primary key and the version column are
-- excluded — the first is a SERIAL, the second is what we are rewriting.
--
-- NOT idempotent by itself; migrate.py applies each file exactly once and
-- records it in admin.schema_migrations, inside the same transaction.
--
-- AFTER APPLYING: the deployment must run an openrailrouting instance for
-- graph key 'infra_2032', or the three new scenarios answer 503
-- routing_graph_not_configured on compute. See
-- backend/models/route/routing/README.md and backend/docker/.env.example.

DO $$
DECLARE
    target   record;
    col_list text;
BEGIN
    FOR target IN
        SELECT *
        FROM (VALUES
            ('track_infrastructures',         'track_infra_row_id',      'track_infra_version'),
            ('track_infrastructure_defaults', 'track_infra_default_id',  'track_infra_default_version'),
            ('stop_infrastructures',          'stop_infra_row_id',       'stop_infra_version'),
            ('stop_infrastructure_defaults',  'stop_infra_default_id',   'stop_infra_default_version'),
            ('passage_charges',               'passage_row_id',          'passage_version')
        ) AS t(table_name, pk_column, version_column)
    LOOP
        SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
          INTO col_list
          FROM information_schema.columns
         WHERE table_schema = 'input_params'
           AND table_name = target.table_name
           AND column_name NOT IN (target.pk_column, target.version_column);

        IF col_list IS NULL THEN
            RAISE EXCEPTION 'input_params.% not found', target.table_name;
        END IF;

        EXECUTE format(
            'INSERT INTO input_params.%I (%s, %I)
             SELECT %s, %I + 4
               FROM input_params.%I
              WHERE %I IN (1, 2, 3)',
            target.table_name, col_list, target.version_column,
            col_list, target.version_column,
            target.table_name,
            target.version_column
        );

        RAISE NOTICE 'input_params.%: versions 5-7 written', target.table_name;
    END LOOP;
END $$;

-- Guard: every new version must be a COMPLETE snapshot of its 2026 source.
-- A partial copy is the one failure this migration could plausibly produce
-- and the one the full-snapshot contract cannot tolerate, so it is checked
-- here rather than left to the test suite (which never sees a server DB).
DO $$
DECLARE
    source_rows integer;
    copied_rows integer;
BEGIN
    SELECT count(*) INTO source_rows
      FROM input_params.track_infrastructures WHERE track_infra_version IN (1, 2, 3);
    SELECT count(*) INTO copied_rows
      FROM input_params.track_infrastructures WHERE track_infra_version IN (5, 6, 7);
    IF source_rows <> copied_rows THEN
        RAISE EXCEPTION
            'track_infrastructures: copied % rows from % source rows',
            copied_rows, source_rows;
    END IF;
END $$;

INSERT INTO scenario.scenarios (
    scenario_key,
    scenario_name,
    description,
    change_log,
    editor,
    is_current_base,
    is_current_scenario,
    track_infrastructures_version,
    track_infrastructure_defaults_version,
    stop_infrastructures_version,
    stop_infrastructure_defaults_version,
    passage_charges_version,
    routing_graph_key
) VALUES
(
    'infra-2032',
    'Infra 2032',
    'The rail network as it is expected to exist in 2032, including the fixed '
    'links and line upgrades now under construction or firmly committed. Night '
    'trains still run on conventional lines only, and their timetables still '
    'carry the generous padding real night trains carry today. What changes '
    'against Infra 2026 is the track itself: journeys that take a long detour '
    'today become direct.',
    'Initial seed. Mirrors Infra 2026 on the infra_2032 routing graph; crossing '
    'charges copied unchanged — see models/scenarios/README.md.',
    'david', FALSE, TRUE, 5, 5, 5, 5, 5, 'infra_2032'
),
(
    'infra-2032-hsr',
    'Infra 2032 + night trains on high-speed lines',
    'The 2032 network, with night trains additionally allowed to use high-speed '
    'lines. The same policy change as in the 2026 equivalent, asked of a network '
    'that by then has more high-speed line to open up.',
    'Initial seed. Mirrors Infra 2026 + NT on HSR on the infra_2032 routing graph.',
    'david', FALSE, TRUE, 6, 6, 6, 6, 6, 'infra_2032'
),
(
    'infra-2032-hsr-opt-tt',
    'Infra 2032 + night trains on high-speed lines + optimised timetables',
    'The most favourable of the six scenarios: everything currently being built, '
    'night trains permitted on high-speed lines, and well-designed paths rather '
    'than the residual ones they are given today. Read it as the upper bound of '
    'what is achievable without new projects beyond those already committed.',
    'Initial seed. Mirrors Infra 2026 + NT on HSR + optimised timetables on the '
    'infra_2032 routing graph. Schedule supplement provisional — see '
    'models/scenarios/README.md.',
    'david', FALSE, TRUE, 7, 7, 7, 7, 7, 'infra_2032'
);
