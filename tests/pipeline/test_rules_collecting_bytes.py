"""Exact confidence normalization stays per-rule in collecting byte loads."""

import pytest

from finjuice.pipeline.tagging.rules_yaml_io import load_rules_collecting_bytes


def test_collecting_exact_confidence_failure_does_not_drop_valid_rules() -> None:
    content = (
        b"rules:\n"
        b"  - name: bad\n"
        b"    match: x\n"
        b"    fields: [merchant_raw]\n"
        b"    tags: [x]\n"
        b"    confidence: 1.0e999\n"
        b"  - name: good\n"
        b"    match: x\n"
        b"    fields: [merchant_raw]\n"
        b"    tags: [x]\n"
        b"    confidence: 0.75\n"
    )
    result = load_rules_collecting_bytes(content)
    assert len(result.errors) == 1 and result.errors[0].rule_index == 0
    assert len(result.rules) == 1 and result.rules[0].confidence == 0.75


def test_collecting_parse_error_does_not_expose_source() -> None:
    with pytest.raises(ValueError) as error:
        load_rules_collecting_bytes(b"PRIVATE_SENTINEL: [")
    assert "PRIVATE_SENTINEL" not in str(error.value)
