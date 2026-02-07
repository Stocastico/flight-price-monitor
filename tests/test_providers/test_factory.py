"""Tests for the provider factory."""

from __future__ import annotations

import pytest

from flight_monitor.config import (
    AppConfig,
    CredentialsConfig,
    DestinationConfig,
    KiwiCredentials,
    OriginConfig,
)
from flight_monitor.providers.factory import create_provider
from flight_monitor.providers.kiwi import KiwiProvider


def _make_config(provider: str = "kiwi", **kwargs) -> AppConfig:
    return AppConfig(
        provider=provider,
        credentials=kwargs.get(
            "credentials",
            CredentialsConfig(kiwi=KiwiCredentials(api_key="test-key")),
        ),
        origins=[OriginConfig(code="BIO")],
        destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
    )


class TestProviderFactory:
    def test_creates_kiwi_provider(self):
        config = _make_config(provider="kiwi")
        provider = create_provider(config)
        assert isinstance(provider, KiwiProvider)
        assert provider.name() == "kiwi"

    def test_raises_on_unknown_provider(self):
        config = _make_config(provider="unknown_provider")
        with pytest.raises(ValueError, match="Unknown provider"):
            create_provider(config)

    def test_raises_on_missing_kiwi_credentials(self):
        config = _make_config(
            provider="kiwi",
            credentials=CredentialsConfig(),
        )
        with pytest.raises(ValueError, match="Kiwi credentials"):
            create_provider(config)

    def test_raises_on_missing_amadeus_credentials(self):
        config = _make_config(
            provider="amadeus",
            credentials=CredentialsConfig(),
        )
        with pytest.raises(ValueError, match="Amadeus credentials"):
            create_provider(config)
