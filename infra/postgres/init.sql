-- Runs once when the PostgreSQL volume is empty. The `actron` database comes from POSTGRES_DB.
CREATE DATABASE temporal OWNER actron;
CREATE DATABASE temporal_visibility OWNER actron;
