SELECT format('CREATE ROLE agrilink_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_password') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agrilink_app') \gexec
ALTER ROLE agrilink_app PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
SELECT 'CREATE DATABASE agrilink OWNER agrilink_app ENCODING ''UTF8''' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'agrilink') \gexec
