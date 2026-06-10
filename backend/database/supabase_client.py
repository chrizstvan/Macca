"""Supabase client initialisation and connection verification.

Exports a module-level ``db`` client instance. Import it anywhere with::

    from backend.database.supabase_client import db
"""

import logging

from supabase import Client, create_client

from backend.config import settings

logger = logging.getLogger(__name__)

db: Client = create_client(settings.supabase_url, settings.supabase_key)


async def test_connection() -> bool:
    """Verify the Supabase connection by running a trivial query.

    Returns True if the database responds, False otherwise.
    """
    try:
        db.table("missions").select("id").limit(1).execute()
        logger.info("Supabase connection verified")
        return True
    except Exception as exc:
        logger.error("Supabase connection test failed: %s", exc)
        return False
