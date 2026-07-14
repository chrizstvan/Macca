"""Decorator-based intent registry for the router.

Lets each specialist agent declare the intent it serves alongside its
class definition, so adding a new intent is a single-file change:

    @register_intent(
        name="...",
        description="...",
        examples=("...", "..."),
    )
    class MyAgent(BaseAgent):
        ...

The router reads the registry at runtime — there's no need to keep a
parallel ``VALID_INTENTS`` tuple, agent dict, or classification prompt in
sync. ``build_classification_prompt`` regenerates the Claude prompt from
the current registry contents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from .base_agent import BaseAgent

ROUTER_HEADER = (
    "Kamu adalah router untuk Chris-Fasil-GBP, platform koordinasi volunteer pengumpulan "
    "sampah plastik di Jakarta. Klasifikasikan pesan volunteer ke dalam TEPAT "
    "SATU kategori berikut. Balas HANYA dengan string kategorinya, tanpa "
    "tanda baca atau penjelasan apa pun."
)


@dataclass(frozen=True)
class IntentSpec:
    """Metadata required to route to a specialist agent."""

    name: str
    description: str
    agent_cls: type
    examples: tuple[str, ...] = field(default_factory=tuple)


_registry: dict[str, IntentSpec] = {}


T = TypeVar("T")


def register_intent(
    *,
    name: str,
    description: str,
    examples: tuple[str, ...] = (),
) -> Callable[[type[T]], type[T]]:
    """Class decorator that adds an agent class to the intent registry.

    Decorated classes keep their identity — the decorator just records
    metadata in the module-level registry. Re-registering the same name
    overwrites the previous entry (handy for hot-reload in tests).
    """

    def _wrap(cls: type[T]) -> type[T]:
        _registry[name] = IntentSpec(
            name=name,
            description=description,
            agent_cls=cls,
            examples=tuple(examples),
        )
        return cls

    return _wrap


def get_intents() -> dict[str, IntentSpec]:
    """Snapshot of the current registry, in insertion order."""
    return dict(_registry)


def get_intent_names() -> tuple[str, ...]:
    return tuple(_registry.keys())


def instantiate_agents() -> dict[str, "BaseAgent"]:
    """Build a ``{name: agent_instance}`` map for the router.

    Each entry calls the registered class with no arguments. Specialist
    agents are expected to follow that contract; tests that need DI can
    instead hand-build the dict and pass it to ``RouterAgent``.
    """
    return {name: spec.agent_cls() for name, spec in _registry.items()}


def build_classification_prompt() -> str:
    """Render the few-shot router prompt from the registry contents."""
    if not _registry:
        return ROUTER_HEADER

    category_lines = "\n".join(
        f"- {spec.name}: {spec.description}" for spec in _registry.values()
    )
    example_lines = "\n".join(
        f'"{example}" → {spec.name}'
        for spec in _registry.values()
        for example in spec.examples
    )
    body = f"{ROUTER_HEADER}\n\nKategori:\n{category_lines}"
    if example_lines:
        body += f"\n\nContoh:\n{example_lines}"
    return body
