#!/usr/bin/env bash
# Build the demo database from scratch and start Odoo.
#
#   1. fresh Odoo database with Sales, Inventory and Invoicing
#   2. one year of simulated order-to-cash history (simulate_company.py)
#   3. a one-day API key for the admin user, written to demo/.env.local
#
# Needs Docker. Takes about 4 minutes.
#
#   bash demo/build_demo.sh                              # Odoo 19 on port 8069
#   ODOO_VERSION=18.0 ODOO_PORT=8169 bash demo/build_demo.sh
#   ODOO_VERSION=17.0 ODOO_PORT=8269 bash demo/build_demo.sh
set -euo pipefail
cd "$(dirname "$0")"
DB="${DB:-xray}"
export ODOO_VERSION="${ODOO_VERSION:-19.0}"
export ODOO_PORT="${ODOO_PORT:-8069}"
# Odoo 18 and older install demo data unless told not to.
DEMO_FLAG=""
case "$ODOO_VERSION" in 1[0-8].*) DEMO_FLAG="--without-demo=all";; esac

docker compose up -d --wait db
docker compose stop odoo >/dev/null 2>&1 || true
docker compose exec -T db dropdb -U odoo --if-exists "$DB"

echo "Creating database '$DB' on Odoo $ODOO_VERSION..."
docker compose run --rm -T odoo odoo -d "$DB" -i sale_management,stock,account \
  --stop-after-init --no-http --log-level=warn $DEMO_FLAG

echo "Simulating one year of orders..."
docker compose run --rm -T odoo odoo shell -d "$DB" --no-http --log-level=warn < simulate_company.py

docker compose run --rm -T odoo odoo shell -d "$DB" --no-http --log-level=warn < make_api_key.py \
  | grep -o "XRAY_API_KEY=.*" > .env.local

docker compose up -d odoo
for _ in $(seq 1 60); do
  curl -sf "http://localhost:$ODOO_PORT/web/health" >/dev/null && break
  sleep 2
done
echo "Odoo $ODOO_VERSION is running on http://localhost:$ODOO_PORT (login admin / admin). API key in demo/.env.local"
