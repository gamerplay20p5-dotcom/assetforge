-- Banco e usuário EXCLUSIVOS do AssetForge em um PostgreSQL existente (ex.: o servidor dedicado de banco).
-- NÃO é executado por nenhum script do projeto: quem administra o servidor roda, UMA vez, como superusuário, trocando a senha.
-- Não toca em nenhum outro banco/usuário. Exemplo (adapte ao seu acesso):
--   psql -U <superusuario> -d postgres -f scripts/db/create_assetforge_db.sql
-- O AssetForge só precisa de permissão no PRÓPRIO banco (cria suas tabelas ao subir).

CREATE ROLE assetforge LOGIN PASSWORD 'TROQUE-ESTA-SENHA' NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 20;
CREATE DATABASE assetforge OWNER assetforge ENCODING 'UTF8';
REVOKE ALL ON DATABASE assetforge FROM PUBLIC;
GRANT CONNECT ON DATABASE assetforge TO assetforge;
-- (opcional) restringir por rede em pg_hba.conf:  host assetforge assetforge <IP_DA_MAQUINA_DO_ASSETFORGE>/32 scram-sha-256
