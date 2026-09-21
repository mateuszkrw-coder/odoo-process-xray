"""Print a one-day API key for the admin user (demo database only).

    odoo shell -d xray --no-http < make_api_key.py
"""
from datetime import datetime, timedelta

admin = env.ref("base.user_admin")
keys = env["res.users.apikeys"].with_user(admin).sudo()
try:  # Odoo 18+ takes an expiration date, older versions do not
    key = keys._generate(None, "odoo-process-xray demo", datetime.now() + timedelta(days=1))
except TypeError:
    key = keys._generate(None, "odoo-process-xray demo")
env.cr.commit()
print("XRAY_API_KEY=" + key)
