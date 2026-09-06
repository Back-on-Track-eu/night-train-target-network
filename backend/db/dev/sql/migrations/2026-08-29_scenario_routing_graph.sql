-- 2026-08-29_scenario_routing_graph.sql
-- =====================================
-- Scenario-dependent routing infrastructure, step 1 (backend plumbing for
-- a second OpenRailRouting instance): every scenario pins the routing
-- graph it routes on, alongside its five *_version snapshot pins.
--
-- All existing rows route on today's network — key 'infra_2026'. The
-- 2032 graph (Jasper's upgraded-network OSM) arrives as NEW scenario
-- rows pinning 'infra_2032'; existing pinned rows are immutable and are
-- never repointed (versioning contract, db/README.md).

ALTER TABLE scenario.scenarios
    ADD COLUMN routing_graph_key VARCHAR(50);

UPDATE scenario.scenarios
    SET routing_graph_key = 'infra_2026';

ALTER TABLE scenario.scenarios
    ALTER COLUMN routing_graph_key SET NOT NULL;

COMMENT ON COLUMN scenario.scenarios.routing_graph_key IS
    'Routing graph this scenario routes on — the physical rail network '
    '(OSM state) behind every distance and travel time, e.g. "infra_2026" '
    'or "infra_2032". Pinned like the *_version columns but not itself a '
    'snapshot version: the graph lives outside the database, in an '
    'OpenRailRouting instance. Naming contract with the deployment: key '
    '<k> is served by the instance at env OPENRAILROUTING_URL_<K> (suffix '
    'uppercased; the bare OPENRAILROUTING_URL serves infra_2026) — see '
    'api/helpers/dependencies.py. The TAC and passage changes an upgraded '
    'network implies are NOT carried here; they ride this same row''s '
    'track_infrastructures_version and passage_charges_version pins.';
