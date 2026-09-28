"""Port registry tests — Pillar 0 §3–§5 dependency inversion (docs/04 §6, 2026-09-28).

The registry is the one place where a port's implementing adapter is bound to
its consumer: `worker`/`media` may not import `sources`, so they ask `core`
for the adapter instead. These tests pin the four behaviours that binding
relies on: absence raises, registration returns a fresh instance per call,
re-registration replaces, and `reset` restores absence (tests only).
"""
from __future__ import annotations

import pytest

from core import registry
from core.api import (
    PassthroughTransformer,
    PortNotRegistered,
    SourceProvider,
    TransformInput,
    get_destination_platform,
    get_metadata_transformer,
    get_source_provider,
    register_destination_platform,
    register_metadata_transformer,
    register_source_provider,
    reset_port_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Empty the registry for one test, then put the process wiring back.

    Snapshot/restore rather than clear: `ui.apps` registers the real provider
    at startup, and a bare `reset()` here would strand every later test that
    expects the process to be wired the way production is.
    """
    snapshot = dict(registry._PORTS)
    reset_port_registry()
    yield
    reset_port_registry()
    registry._PORTS.update(snapshot)


class FakeProvider:
    """Structurally satisfies the SourceProvider protocol (Pillar 0 §3)."""

    def resolve(self, raw_url):  # pragma: no cover - shape only
        raise NotImplementedError

    def scan(self, source, since):  # pragma: no cover - shape only
        raise NotImplementedError

    def hydrate(self, item):  # pragma: no cover - shape only
        raise NotImplementedError

    def materialize(self, request):  # pragma: no cover - shape only
        raise NotImplementedError


class TestPortRegistry:
    def test_unregistered_port_raises_with_the_port_name(self):
        with pytest.raises(PortNotRegistered) as excinfo:
            get_source_provider()
        assert excinfo.value.port == "source_provider"
        assert "source_provider" in str(excinfo.value)

    def test_registered_factory_is_called_on_every_get(self):
        created: list[FakeProvider] = []

        def factory():
            instance = FakeProvider()
            created.append(instance)
            return instance

        register_source_provider(factory)
        first = get_source_provider()
        second = get_source_provider()
        assert first is not second          # a factory, not a singleton cache
        assert created == [first, second]

    def test_registered_instance_satisfies_the_protocol(self):
        register_source_provider(FakeProvider)
        assert isinstance(get_source_provider(), SourceProvider)

    def test_re_registration_replaces_the_factory(self):
        register_source_provider(lambda: FakeProvider())
        replacement = object()
        register_source_provider(lambda: replacement)
        assert get_source_provider() is replacement

    def test_ports_are_independent_keys(self):
        register_source_provider(lambda: FakeProvider())
        with pytest.raises(PortNotRegistered):
            get_destination_platform()

    def test_reset_removes_every_registration(self):
        register_source_provider(lambda: FakeProvider())
        register_destination_platform(lambda: object())
        reset_port_registry()
        with pytest.raises(PortNotRegistered):
            get_source_provider()
        with pytest.raises(PortNotRegistered):
            get_destination_platform()

    def test_metadata_transformer_defaults_to_passthrough(self):
        # v1: no registration needed — the pass-through default is the design.
        transformer = get_metadata_transformer()
        assert isinstance(transformer, PassthroughTransformer)
        result = transformer.transform(
            TransformInput(
                source_title="t",
                source_description="d",
                source_tags=("a",),
                target_language=None,
                template_name=None,
            )
        )
        assert result.applied is False
        assert result.fallback_reason == "transformer_disabled"

    def test_registered_metadata_transformer_overrides_the_default(self):
        sentinel = object()
        register_metadata_transformer(lambda: sentinel)
        assert get_metadata_transformer() is sentinel
