"""LLM completion port — providers and models are swappable behind this."""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """A single ``complete`` call abstracts away vendor SDKs.

    ``messages`` follows the role/content shape Claude uses today (and
    that the OpenAI SDK also accepts), so swapping to a different vendor
    only changes the adapter, not the use cases.
    """

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> str: ...
