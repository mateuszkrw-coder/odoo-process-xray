#!/usr/bin/env bash
# Build the demo database from scratch and start Odoo on http://localhost:8069
#
#   1. fresh Odoo 19 database with Sales, Inventory and Invoicing
#   2. one year of simulated order-to-cash history (simulate_company.py)
#   3. a one-day API key for the admin user, written to demo/.env.local
#
# Needs Docker. Takes about 4 minutes.
set -euo pipefail
cd "$(dirname "$0")"
DB="${DB:-xray}"

docker compose up -d --wait db
docker compose stop odoo >/dev/null 2>&1 || true
docker compose exec -T db dropdb -U odoo --if-exists "$DB"

echo "Creating database '$DB'..."
docker compose run --rm -T odoo odoo -d "$DB" -i sale_management,stock,account \
  --stop-after-init --no-http --log-level=warn

echo "Simulating one year of orders..."
docker compose run --rm -T odoo odoo shell -d "$DB" --no-http --log-level=warn < simulate_company.py

docker compose run --rm -T odoo odoo shell -d "$DB" --no-http --log-level=warn < make_api_key.py \
  | grep -o "XRAY_API_KEY=.*" > .env.local

docker compose up -d odoo
for _ in $(seq 1 60); do
  curl -sf http://localhost:8069/web/health >/dev/null && break
  sleep 2
done
echo "Odoo is running on http://localhost:8069 (login admin / admin). API key in demo/.env.local"
