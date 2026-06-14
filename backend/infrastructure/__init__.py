"""Infrastructure layer — outermost ring.

Concrete adapters fulfilling ``backend.application.ports``. Vendor SDKs
(Supabase, anthropic, httpx, telegram) are imported here only. May
import from ``backend.domain`` and ``backend.application``. Never the
other way around.
"""
