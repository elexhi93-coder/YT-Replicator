from __future__ import annotations

"""
core.registry — the port registry (Pillar 0 §3–§5, "registered adapter").

Pillar 0 defines three replaceable ports (`SourceProvider`,
`DestinationPlatform`, `MetadataTransformer`). The module that *implements* a
port may not be importable by the module that *needs* it — `worker` may not
import `sources`, and `media` may not import `sources` either (docs/04 §2/§3) —
so the dependency has to be inverted at exactly one place.

This is that place. The outermost layer (the Django app config in `ui`, i.e.
process startup) registers a factory; any module may ask for the adapter:

    register_source_provider(YouTubeSourceProvider)   # at startup (ui)
    provider = get_source_provider()                 # inside media / worker

Nothing here imports a sibling module: factories are plain callables and the
adapter is typed by Pillar 0's `Protocol`s, which is why structural typing is
enough. Registering the same port twice replaces the factory, which is what a
test does to install a fake.
"""

from typing import Any, Callable

__all__ = [
    "PortNotRegistered",
    "get_destination_platform",
    "get_metadata_transformer",
    "get_retention_oracle",
    "get_source_provider",
    "register_destination_platform",
    "register_metadata_transformer",
    "register_retention_oracle",
    "register_source_provider",
    "reset_port_registry",
]

Factory = Callable[[], Any]


class PortNotRegistered(RuntimeError):
    """Raised when a port is requested before anything registered it.

    A configuration error, not a domain failure: it means the process started
    without wiring its adapters (see `ui.apps.UiConfig.ready`).
    """

    def __init__(self, port: str) -> None:
        super().__init__(
            f"Port {port!r} is not registered. Register it at process startup "
            "(ui.apps.UiConfig.ready) or install a fake in the test."
        )
        self.port = port


_PORTS: dict[str, Factory] = {}


def register_source_provider(factory: Factory) -> None:
    """Register the `SourceProvider` adapter (v1: `sources.YouTubeSourceProvider`)."""
    _PORTS["source_provider"] = factory


def get_source_provider() -> Any:
    """Return the registered `SourceProvider` instance. Raises `PortNotRegistered`."""
    return _build("source_provider")


def register_destination_platform(factory: Factory) -> None:
    """Register the `DestinationPlatform` adapter (v1: `youtube.YouTubePlatform`)."""
    _PORTS["destination_platform"] = factory


def get_destination_platform() -> Any:
    """Return the registered `DestinationPlatform`. Raises `PortNotRegistered`."""
    return _build("destination_platform")


def register_metadata_transformer(factory: Factory) -> None:
    """Register the `MetadataTransformer` (v1 default: `PassthroughTransformer`)."""
    _PORTS["metadata_transformer"] = factory


def get_metadata_transformer() -> Any:
    """Return the transformer; v1 falls back to the pass-through default."""
    if "metadata_transformer" not in _PORTS:
        from core.ports import PassthroughTransformer

        return PassthroughTransformer()
    return _build("metadata_transformer")


def register_retention_oracle(factory: Factory) -> None:
    """Register the `RetentionOracle` (U12) — the read-only fact snapshot.

    Unlike the other ports there is deliberately **no fallback**: retention
    decides what gets deleted, and a silently-default oracle would let an
    unwired process delete on invented facts. `PortNotRegistered` is the safe
    failure.
    """

    _PORTS["retention_oracle"] = factory


def get_retention_oracle() -> Any:
    """Return the registered `RetentionOracle`. Raises `PortNotRegistered`."""
    return _build("retention_oracle")


def reset_port_registry() -> None:
    """Forget every registration. Tests only — never call it from application code."""
    _PORTS.clear()


def _build(port: str) -> Any:
    factory = _PORTS.get(port)
    if factory is None:
        raise PortNotRegistered(port)
    return factory()
