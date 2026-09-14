"""Detached scenario validation preserves file semantics without file reads."""

from pathlib import Path

import pytest

from finjuice.pipeline.forecast import (
    ScenariosConfig,
    ScenariosConfigValidationError,
    load_scenarios_config,
    load_scenarios_config_bytes,
    validate_scenarios_config_bytes,
)
from finjuice.pipeline.forecast_validators import validate_scenarios_config_file
from tests.pipeline.test_forecast_validators import _write_scenarios


def test_bytes_match_file_with_signed_lifecycle_and_no_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "scenarios.yaml"
    _write_scenarios(
        source,
        """  - name: Bonus
    date: 2026-02-01
    one_time_expense: -2000000
  - name: Support
    start: 2026-03-01
    end: 2026-04-01
    monthly_net_expense: -300000
""",
    )
    content = source.read_bytes()
    expected = validate_scenarios_config_file(source)
    assert expected.is_valid
    expected_config = load_scenarios_config(source)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Detached validation must not read files")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    assert validate_scenarios_config_bytes(content, source_label=source) == expected
    assert load_scenarios_config_bytes(content) == expected_config
    assert expected_config.lifecycle_events[0].one_time_expense == -2000000
    assert expected_config.lifecycle_events[1].monthly_net_expense == -300000


@pytest.mark.parametrize(
    "content,message",
    [
        (b"PRIVATE_SENTINEL: \xff", "invalid UTF-8 encoding"),
        (b"PRIVATE_SENTINEL: [", "invalid YAML syntax"),
    ],
)
def test_static_parser_errors(tmp_path: Path, content: bytes, message: str) -> None:
    source = tmp_path / "scenarios.yaml"
    source.write_bytes(content)
    result = validate_scenarios_config_bytes(content, source_label=source)
    assert result == validate_scenarios_config_file(source)
    assert not result.is_valid
    assert result.issues[0].message == message
    with pytest.raises(ScenariosConfigValidationError) as caught:
        load_scenarios_config_bytes(content)
    assert "PRIVATE_SENTINEL" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "savings",
        "liability",
        "event",
        "unknown",
        "category",
    ],
)
def test_full_semantic_validation_matches_file(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "scenarios.yaml"
    _write_scenarios(source, "  []")
    raw = source.read_text()
    replacements = {
        "version": ("version: 1", "version: 2"),
        "savings": ("default_savings_per_month: 0", "default_savings_per_month: invalid"),
        "liability": ("liability_rate_delta: 0.0", "liability_rate_delta: invalid"),
        "event": ("  []", "  - name: bad\n    date: invalid\n    one_time_expense: 1"),
        "unknown": ("version: 1", "version: 1\nunknown: true"),
        "category": ("real_estate:", "invalid_category:"),
    }
    old, new = replacements[mutation]
    content = raw.replace(old, new).encode()
    source.write_bytes(content)
    result = validate_scenarios_config_bytes(content, source_label=source)
    assert result == validate_scenarios_config_file(source)
    assert not result.is_valid
    with pytest.raises(ScenariosConfigValidationError):
        load_scenarios_config_bytes(content)


def test_missing_file_contract_is_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "missing.yaml"
    assert not validate_scenarios_config_file(source).is_valid
    allowed = validate_scenarios_config_file(source, allow_missing_file=True)
    assert allowed.is_valid and not allowed.exists
    assert load_scenarios_config(source, allow_missing_file=True) == ScenariosConfig()
    with pytest.raises(ScenariosConfigValidationError):
        load_scenarios_config(source)
    assert validate_scenarios_config_bytes(b"").exists
    assert not validate_scenarios_config_bytes(b"").is_valid
