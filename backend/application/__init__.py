"""Application layer — use cases + the ports they depend on.

May import from ``backend.domain``. May NOT import from
``backend.infrastructure`` or any framework SDK (Supabase, anthropic,
httpx, telegram). Infrastructure adapters fulfil these ports and the
composition root wires them up.
"""
