"""Journal writes protect input namespaces and existing notes."""

from pathlib import Path

import pytest

from finjuice.pipeline.cli.commands import journal_repository_output as output
from finjuice.pipeline.config import Config


@pytest.mark.parametrize(
    "relative",
    [
        ".finjuice/note.md",
        "IMPORTS/note.md",
        "transactions/note.md",
        "metadata/note.md",
        "assets/note.md",
        "banksalad/note.md",
        "RULES.YAML",
        "goals.yaml",
        "assets.yaml",
        "scenarios.yaml",
    ],
)
def test_protected_paths_fail_without_mkdir(tmp_path: Path, relative: str) -> None:
    config = Config(data_dir=tmp_path / "data")
    with pytest.raises(ValueError, match="safely outside protected paths"):
        output.validate_journal_destination(config, config.data_dir / relative)
    assert not config.data_dir.exists()


def test_leaf_symlinks_and_resolved_aliases_rejected(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    leaf = tmp_path / "note.md"
    leaf.symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        output.validate_journal_destination(config, leaf)
    alias = tmp_path / "alias"
    alias.symlink_to(config.data_dir / "imports", target_is_directory=True)
    with pytest.raises(ValueError):
        output.validate_journal_destination(config, alias / "note.md")


def test_exclusive_private_publication(tmp_path: Path) -> None:
    config = Config(data_dir=tmp_path / "data")
    target = tmp_path / "notes/note.md"
    assert output.validate_journal_destination(config, target) == target
    assert not target.parent.exists()
    output.write_journal_entry(config, target, "한글 note")
    assert target.read_text() == "한글 note"
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        output.write_journal_entry(config, target, "overwrite")
    assert target.read_text() == "한글 note"
    assert list(target.parent.iterdir()) == [target]


def test_link_failure_cleans_owned_staging(tmp_path: Path, monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("PRIVATE_SOURCE")

    monkeypatch.setattr(output.os, "link", fail)
    target = tmp_path / "notes/note.md"
    with pytest.raises(ValueError) as error:
        output.write_journal_entry(Config(data_dir=tmp_path / "data"), target, "content")
    assert "PRIVATE_SOURCE" not in str(error.value)
    assert list(target.parent.iterdir()) == []


def test_concurrent_destination_creation_is_not_clobbered(tmp_path: Path, monkeypatch) -> None:
    original = output.os.link

    def race(source, target, **kwargs):
        Path(target).write_text("concurrent entry")
        return original(source, target, **kwargs)

    monkeypatch.setattr(output.os, "link", race)
    target = tmp_path / "note.md"
    with pytest.raises(ValueError):
        output.write_journal_entry(Config(data_dir=tmp_path / "data"), target, "new entry")
    assert target.read_text() == "concurrent entry"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_gitignore_links_never_modify_canonical_source(tmp_path: Path, link_kind: str) -> None:
    import os

    config = Config(data_dir=tmp_path / "data")
    config.data_dir.mkdir()
    original = config.data_dir / "rules.yaml"
    original.write_bytes(b"rules: []\n")
    target = tmp_path / ".gitignore"
    if link_kind == "symlink":
        target.symlink_to(original)
        with pytest.raises(ValueError, match="safely"):
            output.write_journal_gitignore(config, target, "_*/\n")
        assert target.is_symlink()
    else:
        os.link(original, target)
        output.write_journal_gitignore(config, target, "_*/\n")
        assert target.read_text() == "_*/\n"
        assert target.stat().st_ino != original.stat().st_ino
    assert original.read_bytes() == b"rules: []\n"


@pytest.mark.parametrize("canonical", [False, True])
def test_gitignore_prompt_appends_via_optional_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    canonical: bool,
) -> None:
    from finjuice.pipeline.cli.commands import journal_gitignore

    (tmp_path / ".git").mkdir()
    journal = tmp_path / "_journal"
    journal.mkdir()
    target = tmp_path / ".gitignore"
    target.write_text("# existing")
    monkeypatch.setattr(journal_gitignore.typer, "confirm", lambda *args, **kwargs: True)
    config = Config(data_dir=tmp_path / "data")
    calls = []

    def writer(path: Path, content: str) -> None:
        calls.append(path)
        output.write_journal_gitignore(config, path, content)

    if canonical:
        journal_gitignore._maybe_prompt_for_gitignore(journal, writer=writer)
    else:
        journal_gitignore._maybe_prompt_for_gitignore(journal)
    assert target.read_text() == "# existing\n_*/\n"
    assert calls == ([target] if canonical else [])
    journal_gitignore._maybe_prompt_for_gitignore(journal, writer=writer)
    assert target.read_text() == "# existing\n_*/\n"
    assert calls == ([target] if canonical else [])
