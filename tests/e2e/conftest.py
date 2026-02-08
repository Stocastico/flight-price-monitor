"""Fixtures for end-to-end tests using recorded HTTP responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from flight_monitor.config import (
    AnalysisConfig,
    AppConfig,
    CredentialsConfig,
    DestinationConfig,
    FiltersConfig,
    KiwiCredentials,
    OriginConfig,
    SearchConfig,
    StorageConfig,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
KIWI_SEARCH_URL = "https://tequila-api.kiwi.com/v2/search"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


@pytest.fixture
def e2e_config(tmp_path) -> AppConfig:
    """A realistic config with two origins and two destinations."""
    return AppConfig(
        provider="kiwi",
        credentials=CredentialsConfig(kiwi=KiwiCredentials(api_key="e2e-test-key")),
        origins=[
            OriginConfig(code="BIO", city="Bilbao"),
            OriginConfig(code="EAS", city="San Sebastián"),
        ],
        destinations=[
            DestinationConfig(name="Berlin", airports=["BER"]),
            DestinationConfig(name="Bergamo", airports=["BGY"]),
        ],
        search=SearchConfig(date_range_days=30, max_results_per_route=10),
        filters=FiltersConfig(
            max_stops=1,
            max_duration_minutes=600,
            departure_time_earliest="06:00",
            departure_time_latest="22:00",
        ),
        analysis=AnalysisConfig(deal_threshold_pct=25.0, min_history_count=3),
        storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
    )


@pytest.fixture
def e2e_config_single(tmp_path) -> AppConfig:
    """Config with a single origin and destination for simpler tests."""
    return AppConfig(
        provider="kiwi",
        credentials=CredentialsConfig(kiwi=KiwiCredentials(api_key="e2e-test-key")),
        origins=[OriginConfig(code="BIO", city="Bilbao")],
        destinations=[DestinationConfig(name="Berlin", airports=["BER"])],
        search=SearchConfig(date_range_days=30, max_results_per_route=10),
        filters=FiltersConfig(),
        analysis=AnalysisConfig(deal_threshold_pct=25.0, min_history_count=3),
        storage=StorageConfig(db_path=str(tmp_path / "e2e_test.db")),
    )


def register_kiwi_routes(fixture_map: dict[str, str]) -> None:
    """Register Kiwi API responses for given origin->fixture mappings.

    fixture_map keys are (fly_from, fly_to) tuples, values are fixture filenames.
    """
    for (fly_from, fly_to), fixture_name in fixture_map.items():
        fixture_data = _load_fixture(fixture_name)

        def make_callback(data: dict, from_code: str, to_code: str):
            def callback(request):
                # Verify the request has correct params
                assert request.params.get("fly_from") == from_code
                assert request.params.get("fly_to") == to_code
                return (200, {}, json.dumps(data))

            return callback

        responses.add_callback(
            responses.GET,
            KIWI_SEARCH_URL,
            callback=make_callback(fixture_data, fly_from, fly_to),
            match=[responses.matchers.query_param_matcher({"fly_from": fly_from, "fly_to": fly_to}, strict_match=False)],
        )
