import os

from supabase import Client, create_client

# Single shared Supabase client for the whole backend. Extracted here -- rather
# than created inline in app/main.py -- so that both main.py and the roadmap
# package (app/roadmap/services.py) can persist to and read from Supabase through
# one client without importing main.py (which would create an import cycle:
# main -> roadmap.routes -> roadmap.services -> main).
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase environment variables!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
