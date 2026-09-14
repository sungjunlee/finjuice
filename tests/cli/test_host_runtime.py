"""Pinned-root trusted host invokes the real CLI without changing CSV defaults."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import finjuice
from finjuice import get_version
from finjuice.pipeline.cli.host_runtime import (
    _ERROR,
    _parse_host_args,
    main,
    open_trusted_host,
    trusted_cli_context,
)
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ExitCode
from finjuice.pipeline.storage.authority import ActivationEvidence, AuthorityPaths
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityIntegrityError,
    BackupVerificationError,
)
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_fixture
from tests.conftest import cli_text

query_root = _query_fixture


@dataclass(frozen=True)
class HostedRoot:
    root: QueryRoot
    enrollment: Path
    digest: str
    artifacts: Path


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _package_files() -> dict[str, bytes]:
    root = Path(finjuice.__file__).expanduser().absolute().parent
    files: dict[str, bytes] = {}
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != "__pycache__")
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            path = Path(current) / name
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    assert files
    return files


def _wheel(files: dict[str, bytes], version: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            f"finjuice-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: finjuice\nVersion: {version}\n\n",
        )
        for relative, data in files.items():
            archive.writestr(f"finjuice/{relative}", data)
    return stream.getvalue()


def _write_release(directory: Path, evidence: ActivationEvidence, wheel: bytes) -> None:
    lock = b"version = 1\n# synthetic independently retained lock\n"
    binding = {
        "binding_schema_version": 1,
        "package_name": "finjuice",
        "release_version": evidence.installed_release_version,
        "release_artifact_sha256": evidence.installed_release_artifact_sha256,
        "dependency_lock_sha256": _digest(lock),
        "source_commit": "a" * 40,
        "build_id": "hosted-runtime.1",
    }
    directory.mkdir(parents=True)
    (directory / f"finjuice-{evidence.installed_release_version}-py3-none-any.whl").write_bytes(
        wheel
    )
    (directory / "dependency.lock").write_bytes(lock)
    (directory / "binding.json").write_bytes(json.dumps(binding).encode())


def _rewrite_activation(root: Path, evidence: ActivationEvidence) -> None:
    path = AuthorityPaths.for_data_dir(root).activation
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["release_version"] = evidence.installed_release_version
    payload["release_artifact_sha256"] = evidence.installed_release_artifact_sha256
    payload["migration_manifest_sha256"] = evidence.verified_migration_manifest_sha256
    payload["pre_cutover_backup_manifest_sha256"] = (
        evidence.verified_pre_cutover_backup_manifest_sha256
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _enrollment_bytes(
    data_root: Path,
    evidence: ActivationEvidence,
    artifacts: Path,
    *,
    changes: dict[str, object] | None = None,
) -> bytes:
    binding = artifacts / "binding.json"
    payload: dict[str, object] = {
        "data_root": str(data_root.expanduser().absolute()),
        "activation_evidence": {
            "installed_release_version": evidence.installed_release_version,
            "installed_release_artifact_sha256": evidence.installed_release_artifact_sha256,
            "verified_migration_manifest_sha256": evidence.verified_migration_manifest_sha256,
            "verified_pre_cutover_backup_manifest_sha256": (
                evidence.verified_pre_cutover_backup_manifest_sha256
            ),
        },
        "release": {
            "binding_sha256": _digest(binding.read_bytes()),
            "activation_evidence": {
                "installed_release_version": evidence.installed_release_version,
                "installed_release_artifact_sha256": evidence.installed_release_artifact_sha256,
                "verified_migration_manifest_sha256": evidence.verified_migration_manifest_sha256,
                "verified_pre_cutover_backup_manifest_sha256": (
                    evidence.verified_pre_cutover_backup_manifest_sha256
                ),
            },
        },
        "artifacts": {
            "wheel": str(
                (
                    artifacts / f"finjuice-{evidence.installed_release_version}-py3-none-any.whl"
                ).absolute()
            ),
            "dependency_lock": str((artifacts / "dependency.lock").absolute()),
            "binding": str(binding.absolute()),
        },
        "wheel_basename": f"finjuice-{evidence.installed_release_version}-py3-none-any.whl",
    }
    payload.update(changes or {})
    return json.dumps(payload).encode()


@pytest.fixture(scope="session")
def imported_package_wheel() -> tuple[str, bytes]:
    version = get_version()
    return version, _wheel(_package_files(), version)


def _enroll(
    query_root: QueryRoot,
    tmp_path: Path,
    *,
    files: dict[str, bytes] | None = None,
    imported_wheel: tuple[str, bytes] | None = None,
) -> HostedRoot:
    if files is None and imported_wheel is not None:
        version, wheel = imported_wheel
    else:
        version = get_version()
        wheel = _wheel(_package_files() if files is None else files, version)
    previous = query_root.provider.evidence
    evidence = ActivationEvidence(
        version,
        _digest(wheel),
        previous.verified_migration_manifest_sha256,
        previous.verified_pre_cutover_backup_manifest_sha256,
    )
    artifacts = tmp_path / "retained-release"
    _write_release(artifacts, evidence, wheel)
    _rewrite_activation(query_root.root, evidence)
    enrollment = tmp_path / "retained-enrollment.json"
    raw = _enrollment_bytes(query_root.root, evidence, artifacts)
    enrollment.write_bytes(raw)
    return HostedRoot(query_root, enrollment, _digest(raw), artifacts)


def _invoke(hosted: HostedRoot, argv: list[str]):
    runtime = open_trusted_host(hosted.enrollment, hosted.digest)
    arguments, obj = trusted_cli_context(runtime, argv)
    return CliRunner().invoke(app, arguments, obj=obj)


def _repository_fingerprint(root: Path) -> tuple[str, ...]:
    generations = AuthorityPaths.for_data_dir(root).generations_root
    return tuple(
        sorted(
            f"{path.relative_to(root).as_posix()}:{_digest(path.read_bytes())}"
            for path in generations.rglob("*")
            if path.is_file()
        )
    )


@pytest.fixture
def hosted_root(
    query_root: QueryRoot, tmp_path: Path, imported_package_wheel: tuple[str, bytes]
) -> HostedRoot:
    return _enroll(query_root, tmp_path, imported_wheel=imported_package_wheel)


def test_approved_bound_root_reads_the_same_generation_and_revision(
    hosted_root: HostedRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FINJUICE_DATA_DIR", str(hosted_root.root.legacy))
    result = _invoke(hosted_root, ["status", "--json"])
    payload = json.loads(cli_text(result))
    assert result.exit_code == 0, cli_text(result)
    assert payload["_meta"]["dataset_generation"] == hosted_root.root.generation
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["schema"]["authority"] == "repository"


def test_real_mutation_enters_current_facade_and_records_revision(
    hosted_root: HostedRoot,
) -> None:
    before = json.loads(cli_text(_invoke(hosted_root, ["status", "--json"])))
    result = _invoke(
        hosted_root,
        [
            "rules",
            "add",
            "--name",
            "hosted_runtime",
            "--match",
            "hosted-merchant",
            "--tags",
            "hosted",
            "--json",
        ],
    )
    payload = json.loads(cli_text(result))
    after = json.loads(cli_text(_invoke(hosted_root, ["status", "--json"])))
    assert result.exit_code == 0, cli_text(result)
    assert payload["authority"] == "repository"
    assert payload["committed_revision"] == before["_meta"]["dataset_revision"] + 1
    assert after["_meta"]["dataset_revision"] == payload["committed_revision"]
    assert after["_meta"]["dataset_generation"] == hosted_root.root.generation


def test_nested_ssot_command_retains_host_context(hosted_root: HostedRoot) -> None:
    result = _invoke(hosted_root, ["ssot", "account", "list", "--json"])
    payload = json.loads(cli_text(result))
    assert result.exit_code == 0, cli_text(result)
    assert payload["_meta"]["command"] == "ssot account list"
    assert "accounts" in payload


def test_ordinary_cli_without_provider_stays_fail_closed(query_root: QueryRoot) -> None:
    result = CliRunner().invoke(app, ["--data-dir", str(query_root.root), "status", "--json"])
    assert result.exit_code != 0
    message = json.loads(result.output)["error"]["message"]
    assert "evidence provider" in message or "validated source" in message
    assert str(query_root.root) not in result.output


@pytest.mark.parametrize(
    "kind",
    ["other_root", "changed_release", "changed_evidence", "wrong_digest", "symlink"],
)
def test_mismatched_root_evidence_or_release_is_rejected_without_writes(
    hosted_root: HostedRoot, tmp_path: Path, kind: str
) -> None:
    before_repo = _repository_fingerprint(hosted_root.root.root)
    before_activation = AuthorityPaths.for_data_dir(hosted_root.root.root).activation.read_bytes()
    if kind == "other_root":
        other = tmp_path / "other-root"
        other.mkdir()
        runtime = open_trusted_host(hosted_root.enrollment, hosted_root.digest)
        with pytest.raises(BackupVerificationError, match="enrolled data root"):
            trusted_cli_context(runtime, ["--data-dir", str(other), "status", "--json"])
    elif kind == "changed_release":
        wheel = hosted_root.artifacts / (f"finjuice-{get_version()}-py3-none-any.whl")
        wheel.write_bytes(wheel.read_bytes() + b"\n")
        with pytest.raises(BackupVerificationError, match="independently trusted"):
            open_trusted_host(hosted_root.enrollment, hosted_root.digest)
    elif kind == "changed_evidence":
        path = AuthorityPaths.for_data_dir(hosted_root.root.root).activation
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["release_artifact_sha256"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(AuthorityIntegrityError, match="verified manifest evidence"):
            open_trusted_host(hosted_root.enrollment, hosted_root.digest)
    elif kind == "wrong_digest":
        with pytest.raises(BackupVerificationError, match="enrollment digest"):
            open_trusted_host(hosted_root.enrollment, "0" * 64)
    else:
        linked = tmp_path / "enrollment-link.json"
        linked.symlink_to(hosted_root.enrollment)
        with pytest.raises(BackupVerificationError, match="could not be verified"):
            open_trusted_host(linked, hosted_root.digest)
    assert _repository_fingerprint(hosted_root.root.root) == before_repo
    if kind != "changed_evidence":
        later = AuthorityPaths.for_data_dir(hosted_root.root.root).activation.read_bytes()
        assert later == before_activation
    assert "PRIVATE" not in _ERROR


def test_tiny_wheel_cannot_claim_the_imported_package(
    query_root: QueryRoot, tmp_path: Path
) -> None:
    hosted = _enroll(
        query_root,
        tmp_path,
        files={"__init__.py": b"# synthetic hosted wheel\n"},
    )
    before = _repository_fingerprint(query_root.root)
    with pytest.raises(BackupVerificationError, match="Installed code"):
        open_trusted_host(hosted.enrollment, hosted.digest)
    assert _repository_fingerprint(query_root.root) == before


def test_malformed_enrollment_is_rejected_before_cli(hosted_root: HostedRoot) -> None:
    hosted_root.enrollment.write_bytes(b'{"data_root": "PRIVATE_SENTINEL"}\n')
    digest = _digest(hosted_root.enrollment.read_bytes())
    with pytest.raises(BackupVerificationError, match="could not be verified") as error:
        open_trusted_host(hosted_root.enrollment, digest)
    assert "PRIVATE_SENTINEL" not in str(error.value)


def test_unactivated_root_is_incomplete_before_cli(hosted_root: HostedRoot) -> None:
    payload = json.loads(hosted_root.enrollment.read_bytes())
    payload["data_root"] = str(hosted_root.root.legacy.expanduser().absolute())
    raw = json.dumps(payload).encode()
    hosted_root.enrollment.write_bytes(raw)
    before = _repository_fingerprint(hosted_root.root.root)
    with pytest.raises(BackupVerificationError, match="could not be verified"):
        open_trusted_host(hosted_root.enrollment, _digest(raw))
    assert _repository_fingerprint(hosted_root.root.root) == before


def test_operator_entrypoint_rejects_missing_pin(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit) as raised:
        main(["--json", "status"])
    payload = json.loads(capsys.readouterr().out)
    assert raised.value.exit_code == ExitCode.VALIDATION_ERROR
    assert payload["error"]["message"] == _ERROR
    assert payload["error"]["code"] == "VALIDATION_FAILED"


def test_bound_provider_rejects_another_authority_namespace(
    hosted_root: HostedRoot, tmp_path: Path
) -> None:
    runtime = open_trusted_host(hosted_root.enrollment, hosted_root.digest)
    other = AuthorityPaths.for_data_dir(tmp_path / "unbound")
    with pytest.raises(AuthorityIntegrityError, match="enrolled data root"):
        runtime.provider.evidence_for(other)
    assert (
        runtime.provider.evidence_for(AuthorityPaths.for_data_dir(hosted_root.root.root))
        == runtime.evidence
    )


@pytest.mark.parametrize("prefix", ["-d", "-vd"])
def test_compact_root_argument_cannot_redirect_a_real_mutation(
    hosted_root: HostedRoot, prefix: str
) -> None:
    other = hosted_root.root.legacy
    rules = other / "rules.yaml"
    before = rules.read_bytes() if rules.exists() else None
    with pytest.raises(BackupVerificationError, match="enrolled data root"):
        _invoke(
            hosted_root,
            [
                prefix + str(other),
                "rules",
                "add",
                "--name",
                "other_root_probe",
                "--match",
                "synthetic",
                "--tags",
                "synthetic",
                "--json",
            ],
        )
    assert (rules.read_bytes() if rules.exists() else None) == before


@pytest.mark.parametrize("separator", [[], ["--"]])
def test_host_options_stop_before_command_values(separator: list[str]) -> None:
    command = ["rules", "add", "--match", "--digest", "--tags", "literal"]
    enrollment, digest, forwarded = _parse_host_args(
        ["--enrollment", "/retained.json", "--digest", "a" * 64, *separator, *command]
    )
    assert enrollment == Path("/retained.json")
    assert digest == "a" * 64
    assert forwarded == command


def test_duplicate_host_pin_is_rejected() -> None:
    with pytest.raises(BackupVerificationError):
        _parse_host_args(
            ["--enrollment", "/retained.json", "--digest", "a" * 64, "--digest", "b" * 64, "status"]
        )
