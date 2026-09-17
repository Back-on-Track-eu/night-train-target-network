-- Re-grant a developer role after a DB copy or reseed (roles are not in the dump).
-- Run as the admin role, e.g.:
--   psql -v ON_ERROR_STOP=1 -v dev=<role> -v mode=readonly|readwrite -f grants-developer.sql
-- (create the role first: CREATE ROLE <role> LOGIN PASSWORD '…';)
GRANT CONNECT ON DATABASE target_network TO :"dev";
GRANT pg_read_all_data TO :"dev";
SELECT set_config('tn.dev_role', :'dev', false);
SELECT set_config('tn.dev_mode', :'mode', false);
DO $$
DECLARE s text; r text := current_setting('tn.dev_role');
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, r);
    IF current_setting('tn.dev_mode', true) = 'readwrite' THEN
      EXECUTE format('GRANT CREATE ON SCHEMA %I TO %I', s, r);
      EXECUTE format('GRANT ALL ON ALL TABLES IN SCHEMA %I TO %I', s, r);
      EXECUTE format('GRANT ALL ON ALL SEQUENCES IN SCHEMA %I TO %I', s, r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO %I', s, r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON SEQUENCES TO %I', s, r);
    END IF;
  END LOOP;
END $$;
