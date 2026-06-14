"""Single-responsibility services used by the progress-tracker agent.

These modules carve up what was previously a single ~870-line
``progress_tracker.py``:

* ``pending_state`` — in-memory multi-turn state with TTL.
* ``notifications`` — Telegram / WhatsApp fan-out for alerts.
* ``report_repository`` — Supabase reads/writes for the ``reports`` table.

``progress_tracker`` re-exports the legacy symbols so external imports
(``main.py``, the test suite, the router) keep working unchanged.
"""
