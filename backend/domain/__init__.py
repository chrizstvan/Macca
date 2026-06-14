"""Domain layer — innermost ring of the architecture.

Contains business entities, value objects, and domain errors. Nothing in
this package may import from ``backend.application`` or
``backend.infrastructure`` (or any framework: Supabase, httpx, anthropic,
FastAPI, telegram). Pure stdlib only.

The dependency rule: outer layers depend on the domain; the domain never
depends on outer layers. Adding a new framework / DB / channel should
require zero changes here.
"""
