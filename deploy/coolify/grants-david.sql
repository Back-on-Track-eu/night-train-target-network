-- Re-grant the developer role after a DB copy or reseed (roles are not in the dump).
-- Run as bot_admin: psql -v ON_ERROR_STOP=1 -v mode=readonly|readwrite -f grants-david.sql
-- (create the role first: CREATE ROLE david LOGIN PASSWORD '…';)
GRANT CONNECT ON DATABASE target_network TO david;
GRANT pg_read_all_data TO david;
DO $$
DECLARE s text;
BEGIN
  FOR s IN SELECT nspname FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO david', s);
    IF current_setting('tn.david_mode', true) = 'readwrite' THEN
      EXECUTE format('GRANT CREATE ON SCHEMA %I TO david', s);
      EXECUTE format('GRANT ALL ON ALL TABLES IN SCHEMA %I TO david', s);
      EXECUTE format('GRANT ALL ON ALL SEQUENCES IN SCHEMA %I TO david', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO david', s);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON SEQUENCES TO david', s);
    END IF;
  END LOOP;
END $$;
