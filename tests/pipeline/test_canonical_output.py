"""Derived output cannot overwrite canonical storage or preserved inputs."""

import os

import pytest

from finjuice.pipeline.config import Config
from finjuice.pipeline.export.canonical_output import write_canonical_output


@pytest.mark.parametrize(
    "relative",
    [
        "rules.yaml",
        "assets.yaml",
        "goals.yaml",
        "scenarios.yaml",
        ".finjuice/authority/active.json",
        ".finjuice/generations/g/finjuice.sqlite3",
        "imports/source.xlsx",
        "transactions/2026/08/transactions.csv",
        "metadata/history.json",
        "assets/snapshots/2026/08/assets.csv",
        "banksalad/balances/source.csv",
    ],
)
def test_reserved_output_and_symlink_alias_preserve_inputs(tmp_path, relative):
    config = Config(data_dir=tmp_path / "data")
    target = config.data_dir / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(b"preserved")
    alias = tmp_path / "alias"
    alias.symlink_to(target)

    for output in (target, alias):
        with pytest.raises(ValueError, match="protected input and storage"):
            write_canonical_output(config, output, b"replacement")

    assert target.read_bytes() == b"preserved"
    assert alias.is_symlink()


def test_parent_alias_and_outward_input_alias_are_rejected(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.csv_base_dir.mkdir(parents=True)
    inward = tmp_path / "inward"
    inward.symlink_to(config.csv_base_dir, target_is_directory=True)
    outward = config.csv_base_dir / "outward"
    outward.symlink_to(tmp_path, target_is_directory=True)

    for output in (inward / "new.csv", outward / "new.csv"):
        with pytest.raises(ValueError):
            write_canonical_output(config, output, b"replacement")

    assert not (config.csv_base_dir / "new.csv").exists()
    assert not (tmp_path / "new.csv").exists()


def test_atomic_output_breaks_hardlink_without_editing_original(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    config.rules_file.write_bytes(b"original")
    output = tmp_path / "output.yaml"
    os.link(config.rules_file, output)

    write_canonical_output(config, output, b"# preserved bytes\r\nrules: []\r\n")

    assert config.rules_file.read_bytes() == b"original"
    assert output.read_bytes() == b"# preserved bytes\r\nrules: []\r\n"
    assert output.stat().st_ino != config.rules_file.stat().st_ino


def test_normal_nested_export_output_and_repeat_are_allowed(tmp_path):
    config = Config(data_dir=tmp_path / "data")
    target = config.export_dir / "guides" / "rules.yaml"

    write_canonical_output(config, target, b"first")
    write_canonical_output(config, target, b"second")

    assert target.read_bytes() == b"second"
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize(
    "relative", ["RULES.YAML", ".FINJUICE/authority/active.json", "TRANSACTIONS/new.csv"]
)
def test_case_variants_cannot_publish_into_reserved_namespaces(tmp_path, relative):
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    config.rules_file.write_bytes(b"original")

    with pytest.raises(ValueError, match="protected input and storage"):
        write_canonical_output(config, config.data_dir / relative, b"replacement")

    assert config.rules_file.read_bytes() == b"original"
    assert not (config.data_dir / ".finjuice").exists()
    assert not config.csv_base_dir.exists()


def test_unicode_normalized_input_alias_is_protected(tmp_path):
    config = Config(data_dir=tmp_path / "caf\u00e9")
    config.data_dir.mkdir()
    config.rules_file.write_bytes(b"original")
    alias = tmp_path / "cafe\u0301" / "rules.yaml"

    with pytest.raises(ValueError, match="protected input and storage"):
        write_canonical_output(config, alias, b"replacement")

    assert config.rules_file.read_bytes() == b"original"


@pytest.mark.parametrize("namespace", ["authority", "generations"])
def test_relocated_storage_root_is_protected_by_its_real_path(tmp_path, namespace):
    config = Config(data_dir=tmp_path / "data")
    control = config.data_dir / ".finjuice"
    control.mkdir(parents=True)
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    target = relocated / "preserved"
    target.write_bytes(b"original")
    (control / namespace).symlink_to(relocated, target_is_directory=True)

    with pytest.raises(ValueError, match="protected input and storage"):
        write_canonical_output(config, target, b"replacement")

    assert target.read_bytes() == b"original"
