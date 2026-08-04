"""Core engine interfaces — systems plug in via these contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class IGameSystem(Protocol):
    """A cohesive game subsystem (HR, Research, Market, Compute...)."""

    name: str

    def on_new_game(self, state: dict[str, Any], ctx: "IGameContext") -> None: ...

    def on_tick(self, state: dict[str, Any], ctx: "IGameContext", days: int = 1) -> list[dict]: ...

    def serialize_public(self, state: dict[str, Any], ctx: "IGameContext") -> dict[str, Any]: ...


class EffectApplier(ABC):
    """Applies config-described effect dicts onto game state.

    Effects are plain dicts from JSON, e.g. {"capital": 1000, "gov_relation": 5}.
    Register custom handlers to extend without touching core loops.
    """

    @abstractmethod
    def apply(self, state: dict[str, Any], effects: dict[str, Any], ctx: "IGameContext") -> list[str]:
        ...

    @abstractmethod
    def register(self, key: str, handler: Callable) -> None:
        ...


class IGameContext(ABC):
    """Shared services available to all systems."""

    @abstractmethod
    def configs(self) -> Any: ...

    @abstractmethod
    def rng(self) -> Any: ...

    @abstractmethod
    def effects(self) -> EffectApplier: ...

    @abstractmethod
    def get_system(self, name: str) -> Any: ...

    @abstractmethod
    def log(self, message: str, *, level: str = "info", category: str = "game") -> None: ...

    @abstractmethod
    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None: ...


class SystemRegistry:
    """Holds ordered game systems; tick order is registration order."""

    def __init__(self) -> None:
        self._systems: dict[str, IGameSystem] = {}
        self._order: list[str] = []

    def register(self, system: IGameSystem) -> None:
        if system.name in self._systems:
            raise ValueError(f"System already registered: {system.name}")
        self._systems[system.name] = system
        self._order.append(system.name)

    def get(self, name: str) -> IGameSystem | None:
        return self._systems.get(name)

    def all(self) -> list[IGameSystem]:
        return [self._systems[n] for n in self._order]

    def names(self) -> list[str]:
        return list(self._order)
