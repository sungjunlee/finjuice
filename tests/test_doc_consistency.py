"""Documentation consistency checks for agentic pilot guardrails."""

import re
from pathlib import Path

import yaml


def _iter_markdown_files(base_dir: Path):
    for path in base_dir.rglob("*.md"):
        if "docs/archive" in str(path):
            continue
        yield path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_no_legacy_full_tag_option_in_non_archive_docs() -> None:
    """Non-archive docs should not use unsupported legacy full-tag option."""
    repo_root = _repo_root()

    scan_roots = [
        repo_root / "docs",
        repo_root / "src/finjuice/templates",
        repo_root / "templates",
        repo_root / ".claude",
    ]

    violations: list[str] = []
    needle = "finjuice tag --full"

    for root in scan_roots:
        if not root.exists():
            continue

        for path in _iter_markdown_files(root):
            text = path.read_text(encoding="utf-8")
            if needle in text:
                violations.append(str(path.relative_to(repo_root)))

    assert not violations, f"Found unsupported command pattern '{needle}' in: {violations}"


def test_public_tree_does_not_track_project_claude_readme() -> None:
    """Project-local Claude runtime files stay out of the public source tree."""
    repo_root = _repo_root()

    assert not (repo_root / ".claude/README.md").exists()


def test_readme_uses_current_install_and_pipeline_commands() -> None:
    """README should reference finjuice commands/path, not deprecated banksalad-tools variants."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "uv tool upgrade banksalad-tools" not in readme
    assert "banksalad-tools" not in readme
    assert "finjuice all" not in readme
    assert "~/.finjuice/" in readme


def test_readme_quick_start_is_skill_first_path() -> None:
    """README quick start should lead with skills, then runtime troubleshooting."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    quick_start = readme.split("## 빠른 시작", maxsplit=1)[1].split(
        "\n## AI 에이전트와 함께 쓰기", maxsplit=1
    )[0]

    for required_text in (
        "npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'",
        "finjuice 온보딩 시작해줘",
        "uv tool install git+https://github.com/sungjunlee/finjuice",
        "finjuice doctor --json",
        "finjuice status --json",
        "~/.finjuice/",
    ):
        assert required_text in quick_start

    assert "Homebrew" not in quick_start
    assert "dashboard" not in quick_start.lower()
    assert quick_start.index(
        "npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'"
    ) < quick_start.index("uv tool install git+https://github.com/sungjunlee/finjuice")


def test_duckdb_setup_uses_github_uv_tool_recovery_path() -> None:
    """Analytics setup docs should match the current GitHub uv tool distribution path."""
    repo_root = _repo_root()
    setup_doc = (repo_root / "docs/guides/setup/duckdb-setup.md").read_text(encoding="utf-8")

    assert "uv tool install --with duckdb finjuice" not in setup_doc
    assert (
        "uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice"
        in setup_doc
    )


def test_readme_shows_beginner_friendly_finance_questions() -> None:
    """README should show practical questions before setup details."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    questions = readme.split("## 이런 질문을 해볼 수 있어요", maxsplit=1)[1].split(
        "\n## 무엇을 하나요", maxsplit=1
    )[0]

    for required_text in (
        "지난달 지출",
        "지난 1년 소비 패턴",
        "구독 요금",
        "중복으로 잡힌",
        "카테고리와 태그",
    ):
        assert required_text in questions

    assert readme.index("## 이런 질문을 해볼 수 있어요") < readme.index("## 빠른 시작")


def test_readme_beginner_questions_map_to_skill_workflows() -> None:
    """Beginner prompt examples should stay aligned with the base skill router."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    base_skill = (repo_root / "skills/finjuice/SKILL.md").read_text(encoding="utf-8")

    for readme_phrase, router_phrase in (
        ("지난달 지출에서 평소보다 심하게 늘어난 항목", "지난달 지출"),
        ("지난 1년 소비 패턴", "소비 패턴"),
        ("구독 요금이나 매달 새는 돈", "구독 요금"),
        ("카드 결제나 계좌 이체", "카드 결제나 계좌 이체"),
        ("카테고리와 태그 규칙", "카테고리와 태그 규칙"),
    ):
        assert readme_phrase in readme
        assert router_phrase in base_skill

    for workflow in (
        "`finjuice-onboard`",
        "`finjuice-curate`",
        "`finjuice-review`",
        "`finjuice-report`",
        "`finjuice-rule-cleanup`",
    ):
        assert workflow in base_skill

    assert "### Beginner Core" in base_skill
    assert "### Advanced Explicit Workflows" in base_skill
    assert base_skill.index("### Beginner Core") < base_skill.index(
        "### Advanced Explicit Workflows"
    )


def test_readme_public_workflow_table_stays_beginner_first() -> None:
    """README should not make advanced/high-stakes workflows part of the default surface."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    table = readme.split("대표 workflow:", maxsplit=1)[1].split("\n전체 스킬은", maxsplit=1)[0]

    for workflow in (
        "`finjuice-onboard`",
        "`finjuice-curate`",
        "`finjuice-review`",
        "`finjuice-report`",
        "`finjuice-rule-cleanup`",
    ):
        assert workflow in table

    for advanced in ("finjuice-diagnose", "finjuice-lifecycle-plan", "finjuice-tax-headroom"):
        assert advanced not in table


def test_community_health_files_are_privacy_first() -> None:
    """Public support docs should route users away from sharing financial data."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    support = (repo_root / "SUPPORT.md").read_text(encoding="utf-8")
    conduct = (repo_root / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    governance = (repo_root / "GOVERNANCE.md").read_text(encoding="utf-8")
    issue_config = (repo_root / ".github/ISSUE_TEMPLATE/config.yml").read_text(encoding="utf-8")

    for path in ("SUPPORT.md", "CODE_OF_CONDUCT.md", "GOVERNANCE.md", "SECURITY.md"):
        assert f"]({path})" in readme

    for required_text in (
        "Do not include raw Banksalad exports",
        "transaction rows",
        "synthetic or redacted structure",
        "finjuice version and install method",
        "private paths replaced by placeholders",
    ):
        assert required_text in support

    assert "Pressuring someone to disclose private financial data" in conduct
    assert "CLI JSON schemas" in governance
    assert "blank_issues_enabled: false" in issue_config
    assert "SUPPORT.md" in issue_config


def test_public_agent_smoke_workflow_is_documented() -> None:
    """Public smoke docs should prove agent-first usage without real user data."""
    repo_root = _repo_root()
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    smoke_doc = (repo_root / "docs/guides/public-agent-smoke.md").read_text(encoding="utf-8")

    assert "docs/guides/public-agent-smoke.md" in readme

    for required_text in (
        "tests/fixtures/sample_banksalad.xlsx",
        "uv run python scripts/smoke_agent_workflow.py",
        "skills/finjuice/scripts/ensure_finjuice_cli.sh --json",
        '--require-command "index"',
        '--require-command "export"',
        "FINJUICE_RUNTIME_UPDATE_CHECK=0",
        "init --no-git --with-agents",
        'import --file "$SAMPLE_XLSX" --json',
        "status --json",
        "index --json --privacy compact",
        "checkup --json --privacy compact",
        "template run monthly_spend --json",
        "export --format md --json",
        "Do not use a real export",
    ):
        assert required_text in smoke_doc


def test_agent_package_layout_adr_defers_named_packages() -> None:
    """Agent package layout should be decided without broad skill restructuring."""
    repo_root = _repo_root()
    adr = (
        repo_root
        / "docs/architecture/decisions/0012-agent-package-layout-for-finjuice-workflows.md"
    ).read_text(encoding="utf-8")
    adr_index = (repo_root / "docs/architecture/decisions/README.md").read_text(encoding="utf-8")
    arch_readme = (repo_root / "docs/architecture/README.md").read_text(encoding="utf-8")

    for required_text in (
        "keep `skills/finjuice*` as the canonical package surface",
        "Do not introduce separate named packages",
        "`finjuice-analyst`, `finjuice-curator`, and `finjuice-reporter`",
        "No implementation step is required in this issue",
        "metadata-only bundle labels",
        "Do not introduce duplicate package directories",
        "scripts/validate_agent_package.py",
    ):
        assert required_text in adr

    assert "0012-agent-package-layout-for-finjuice-workflows.md" in adr_index
    assert re.search(r"All \d+ current ADRs", adr_index)
    assert "ADR-0012: Agent Package Layout" in arch_readme


def test_banksalad_overview_workbook_ingest_adr_is_indexed() -> None:
    """Banksalad overview workbook ingest should be captured in ADR indexes."""
    repo_root = _repo_root()
    adr = (
        repo_root / "docs/architecture/decisions/0013-banksalad-overview-workbook-ingest.md"
    ).read_text(encoding="utf-8")
    adr_index = (repo_root / "docs/architecture/decisions/README.md").read_text(encoding="utf-8")
    arch_readme = (repo_root / "docs/architecture/README.md").read_text(encoding="utf-8")

    for required_text in (
        "ingest the whole `뱅샐현황` worksheet as normalized workbook facts",
        "Do not parse `뱅샐현황` by fixed row numbers",
        "The inspect/debug surface may print only metadata",
        "`assets balance`",
    ):
        assert required_text in adr

    assert "0013-banksalad-overview-workbook-ingest.md" in adr_index
    assert "ADR-0013: Banksalad Overview Workbook Ingest" in arch_readme


def test_runtime_update_check_docs_cover_ttl_and_snooze() -> None:
    """Runtime setup docs should explain non-blocking TTL checks and bounded snooze."""
    repo_root = _repo_root()
    docs = [
        repo_root / "docs/guides/setup/ai-agent-setup.md",
        repo_root / "docs/guides/setup/ai-cli-setup.md",
        repo_root / "skills/finjuice/references/runtime-preflight.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "~/.finjuice/agent-runtime-state.json" in text
        assert "--snooze-update-check" in text
        assert "FINJUICE_RUNTIME_UPDATE_CHECK=0" in text
        assert "FINJUICE_AUTO_UPDATE=1" in text


def test_tagging_review_terminology_contract_is_documented() -> None:
    """Status/review/rules JSON terminology should stay explicit and non-overloaded."""
    repo_root = _repo_root()
    terminology = (repo_root / "docs/reference/tagging-review-terminology.md").read_text(
        encoding="utf-8"
    )
    schema_reference = (repo_root / "docs/reference/json-schemas.md").read_text(encoding="utf-8")

    for term in (
        "`untagged`",
        "`uncategorized`",
        "`rule_matched`",
        "`needs_review`",
        "`suggestable_untagged`",
    ):
        assert term in terminology

    for field in (
        "status.tagging.suggestable_untagged_count",
        "status.terminology.reference",
        "automation run.tagging_pressure.suggestable_untagged_transactions",
        "rules suggest.suggestable_untagged_count",
        "review.transactions[].rule_matched",
    ):
        assert field in terminology

    for schema_field in (
        "x-finjuice-field-definitions",
        "suggestable_untagged_count",
        "rule_matched",
    ):
        assert schema_field in schema_reference


def test_finjuice_report_recipes_reference_real_templates() -> None:
    """Report recipes should not drift from the template registry."""
    repo_root = _repo_root()
    recipe_text = (repo_root / "skills/finjuice-report/references/report-recipes.md").read_text(
        encoding="utf-8"
    )
    registry = yaml.safe_load(
        (repo_root / "src/finjuice/templates/sql/registry.yaml").read_text(encoding="utf-8")
    )

    referenced_templates = set(re.findall(r"finjuice template run ([a-z_]+)", recipe_text))
    registered_templates = set(registry["templates"])

    assert referenced_templates
    assert referenced_templates <= registered_templates


def test_finjuice_report_artifact_path_is_consistent() -> None:
    """Report workflow docs should keep one artifact root."""
    repo_root = _repo_root()
    report_docs = [
        repo_root / "skills/finjuice-report/SKILL.md",
        repo_root / "skills/finjuice-report/references/report-recipes.md",
        repo_root / "skills/finjuice/references/report-contract.md",
        repo_root / "docs/workflows/ai-finance-report-dogfood.md",
    ]
    expected_path = "~/.finjuice/exports/ai-reports/"

    for path in report_docs:
        text = path.read_text(encoding="utf-8")
        assert expected_path in text
        assert "data/exports/ai-reports" not in text
        assert "~/.finjuice/reports/ai-reports" not in text


def test_finjuice_report_docs_avoid_removed_cli_analysis_commands() -> None:
    """The report workflow should stay outside removed CLI analysis surfaces."""
    repo_root = _repo_root()
    report_docs = [
        repo_root / "skills/finjuice-report/SKILL.md",
        repo_root / "skills/finjuice-report/references/report-recipes.md",
        repo_root / "skills/finjuice/references/report-contract.md",
        repo_root / "docs/workflows/ai-finance-report-dogfood.md",
    ]
    removed_command_pattern = re.compile(
        r"\bfinjuice\s+(ask|stats|insights|simulate|ai)\b",
        flags=re.IGNORECASE,
    )

    violations = [
        str(path.relative_to(repo_root))
        for path in report_docs
        if removed_command_pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert not violations


def test_finjuice_report_prompt_routing_contract() -> None:
    """Core report/review/curation prompts should remain unambiguous."""
    repo_root = _repo_root()
    base_skill = (repo_root / "skills/finjuice/SKILL.md").read_text(encoding="utf-8")
    review_skill = (repo_root / "skills/finjuice-review/SKILL.md").read_text(encoding="utf-8")
    report_skill = (repo_root / "skills/finjuice-report/SKILL.md").read_text(encoding="utf-8")

    assert "이번 달 리포트 HTML로 만들어줘" in base_skill
    assert "Do not make the workflow depend\non slash commands existing." in base_skill
    for sibling in (
        "finjuice-report",
        "finjuice-review",
        "finjuice-curate",
    ):
        assert f"`{sibling}`" in base_skill
    assert "`/finjuice-report`" not in base_skill
    assert "`/finjuice-review`" not in base_skill

    assert "Do not write saved report artifacts" in review_skill
    assert "`finjuice-report` if available; otherwise follow" in review_skill

    for mode in ("monthly", "yearly", "focus-spending", "cleanup-aware"):
        assert f"`{mode}`" in report_skill

    for removed_surface in (
        "finjuice-tax-headroom",
        "finjuice-lifecycle-plan",
        "tax-headroom",
        "tax deduction headroom report",
    ):
        assert removed_surface not in base_skill
        assert removed_surface not in review_skill
        assert removed_surface not in report_skill

    for prompt in (
        "월간 리포트",
        "연간 리포트",
        "HTML 리포트",
        "spending recap",
        "주요소비 분석",
    ):
        assert prompt in report_skill


def test_storage_contract_docs_mark_csv_as_runtime_ssot() -> None:
    """Live docs should present CSV partitions, not SQLite, as runtime storage."""
    repo_root = _repo_root()
    user_guide = (repo_root / "docs/guides/user_guide.md").read_text(encoding="utf-8")
    csv_adr = (repo_root / "docs/architecture/decisions/0002-csv-partition-storage.md").read_text(
        encoding="utf-8"
    )

    assert "transactions/YYYY/MM/transactions.csv" in user_guide
    assert "CSV partitions are the runtime source of truth" in csv_adr
    assert "does not maintain a parallel database file" in csv_adr


def test_finjuice_skill_suite_paths_exist() -> None:
    """Base skill routing should not reference missing sibling skills or references."""
    repo_root = _repo_root()

    required_paths = [
        "skills/finjuice/SKILL.md",
        "skills/finjuice-onboard/SKILL.md",
        "skills/finjuice-review/SKILL.md",
        "skills/finjuice-report/SKILL.md",
        "skills/finjuice-diagnose/SKILL.md",
        "skills/finjuice-curate/SKILL.md",
        "skills/finjuice-rule-cleanup/SKILL.md",
        "skills/finjuice/references/cli-quick-ref.md",
        "skills/finjuice/references/report-contract.md",
        "skills/finjuice/references/rule-decision-protocol.md",
        "skills/finjuice/references/persistence-policy.md",
        "skills/finjuice/references/runtime-preflight.md",
        "skills/finjuice/references/discovery-guide.md",
        "skills/finjuice/references/final-response-contract.md",
    ]

    missing = [path for path in required_paths if not (repo_root / path).exists()]

    assert not missing


def test_finjuice_skill_sibling_routes_are_provider_neutral() -> None:
    """Sibling routes should include available-skill and inline fallback language."""
    repo_root = _repo_root()
    skill_docs = sorted((repo_root / "skills").glob("finjuice*/**/*.md"))
    route_patterns = [
        re.compile(r"(?<![\w.])`?/finjuice-[a-z0-9-]+`?"),
        re.compile(r"sibling skill\s+`?finjuice-[a-z0-9-]+`?"),
    ]
    violations: list[str] = []

    assert skill_docs

    for path in skill_docs:
        text = path.read_text(encoding="utf-8")
        for pattern in route_patterns:
            for match in pattern.finditer(text):
                paragraph_start = text.rfind("\n\n", 0, match.start()) + 2
                paragraph_end = text.find("\n\n", match.end())
                if paragraph_end == -1:
                    paragraph_end = len(text)
                paragraph = text[paragraph_start:paragraph_end]
                normalized_paragraph = " ".join(paragraph.lower().split())
                has_available_route = (
                    "if available" in normalized_paragraph or "available" in normalized_paragraph
                )
                has_provider_neutral_route = (
                    "sibling skill" in normalized_paragraph and has_available_route
                )
                has_inline_fallback = (
                    "otherwise follow" in normalized_paragraph and "inline" in normalized_paragraph
                ) or (
                    "sibling switching is unavailable" in normalized_paragraph
                    and "follow" in normalized_paragraph
                    and "inline" in normalized_paragraph
                )
                if not (has_provider_neutral_route and has_inline_fallback):
                    line = text.count("\n", 0, match.start()) + 1
                    violations.append(f"{path.relative_to(repo_root)}:{line}: {match.group(0)}")

    assert not violations


def _runtime_preflight_block(skill_text: str) -> str:
    match = re.search(r"(?ms)^## Runtime Preflight\n(?P<body>.*?)(?=^## |\Z)", skill_text)
    assert match, "missing ## Runtime Preflight block"
    return match.group("body")


def _runtime_capabilities(skill_text: str) -> list[str]:
    match = re.search(r"(?m)^- Capabilities: (?P<capabilities>.+)$", skill_text)
    assert match, "missing runtime capabilities"
    return [
        capability.strip().strip("`")
        for capability in match.group("capabilities").split(",")
        if capability.strip()
    ]


def _expected_preflight_gate(capability: str) -> str:
    if "." in capability:
        return f"--require-capability {capability}"
    if capability == "journal":
        return '--require-command "journal new"'
    return f'--require-command "{capability}"'


def test_finjuice_skills_reference_shared_runtime_preflight_reference() -> None:
    """Every finjuice skill should point agents to the shared preflight procedure."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))
    shared_reference = "skills/finjuice/references/runtime-preflight.md"

    assert skill_paths

    missing_reference = [
        str(path.relative_to(repo_root))
        for path in skill_paths
        if shared_reference not in path.read_text(encoding="utf-8")
    ]

    assert not missing_reference


def test_finjuice_runtime_preflight_reference_owns_shared_shell_block() -> None:
    """The long resolver block and update policy should live in one shared reference."""
    repo_root = _repo_root()
    reference = repo_root / "skills/finjuice/references/runtime-preflight.md"
    text = reference.read_text(encoding="utf-8")

    for required in (
        'FINJUICE_ENSURE=""',
        "for candidate in \\",
        "skills/finjuice/scripts/ensure_finjuice_cli.sh",
        "$HOME/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        "$HOME/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        'status: "blocked"',
        "report its `message`",
        "~/.finjuice/agent-runtime-state.json",
        "--snooze-update-check",
        "--update --json",
        "FINJUICE_RUNTIME_UPDATE_CHECK=0",
        "FINJUICE_AUTO_UPDATE=1",
    ):
        assert required in text
    assert re.search(r"do\s+not\s+install `uv`", text)


def test_finjuice_skill_files_do_not_duplicate_shared_runtime_shell_block() -> None:
    """Skill files should keep local gates but not copy the shared resolver or update policy."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))

    assert skill_paths

    violations: list[str] = []
    stale_policy: list[str] = []
    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        if 'FINJUICE_ENSURE=""' in text or "for candidate in \\" in text:
            violations.append(str(path.relative_to(repo_root)))
        if "~/.finjuice/agent-runtime-state.json" in text or "--snooze-update-check" in text:
            stale_policy.append(str(path.relative_to(repo_root)))

    assert not violations
    assert not stale_policy


def test_finjuice_skills_declare_standard_runtime_requirements() -> None:
    """Every finjuice skill should declare local capabilities and matching gates."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))

    assert skill_paths

    missing_contract = []
    missing_capability_gates = []
    for path in skill_paths:
        text = path.read_text(encoding="utf-8")
        preflight = _runtime_preflight_block(text)
        capabilities = _runtime_capabilities(text)
        if (
            "## Runtime Requirements" not in text
            or "Minimum finjuice: `0.6.2`" not in text
            or "Capabilities:" not in text
            or "--require-version 0.6.2" not in preflight
        ):
            missing_contract.append(str(path.relative_to(repo_root)))
        for capability in capabilities:
            expected_gate = _expected_preflight_gate(capability)
            if expected_gate not in preflight:
                missing_capability_gates.append(
                    f"{path.relative_to(repo_root)} missing {expected_gate}"
                )

    assert not missing_contract
    assert not missing_capability_gates


def test_finjuice_skills_use_shared_workspace_discovery_contract() -> None:
    """Skills should start from the shared index/checkup discovery guidance."""
    repo_root = _repo_root()
    guide = (repo_root / "skills/finjuice/references/discovery-guide.md").read_text(
        encoding="utf-8"
    )
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))

    for command in (
        "finjuice index --json --privacy compact",
        "finjuice checkup --json --privacy compact",
        "finjuice status --json",
        "finjuice manifest --json",
    ):
        assert command in guide

    for phrase in (
        "first workspace map",
        "first health snapshot",
        "detailed data health",
        "CLI/API capability discovery",
    ):
        assert phrase in guide

    assert skill_paths
    missing_reference = [
        str(path.relative_to(repo_root))
        for path in skill_paths
        if "discovery-guide.md" not in path.read_text(encoding="utf-8")
    ]
    missing_index_first = [
        str(path.relative_to(repo_root))
        for path in skill_paths
        if "finjuice index --json --privacy compact" not in path.read_text(encoding="utf-8")
    ]
    onboard = (repo_root / "skills/finjuice-onboard/SKILL.md").read_text(encoding="utf-8")

    assert not missing_reference
    assert not missing_index_first
    assert 'collections[]` entry where `name == "transactions"' in onboard
    assert "`status` is\n  `populated`" in onboard


def test_finjuice_skills_keep_blocked_runtime_handling_local() -> None:
    """Every skill should still stop on blocked preflight JSON without installing uv."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))

    assert skill_paths

    missing_blocked_handling = []
    for path in skill_paths:
        preflight = _runtime_preflight_block(path.read_text(encoding="utf-8"))
        if (
            'status: "blocked"' not in preflight
            or "report its `message`" not in preflight
            or not re.search(r"do\s+not\s+install `uv`", preflight)
        ):
            missing_blocked_handling.append(str(path.relative_to(repo_root)))

    assert not missing_blocked_handling


def test_finjuice_skill_fallback_language_is_standardized() -> None:
    """Unsupported CLI paths should use one fallback message and stop recommending them."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))
    required_text = (
        "Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because "
        "the local finjuice runtime lacks required capability `<capability>`. Do not "
        "recommend or run the failed command after preflight failure."
    )

    assert skill_paths

    violations = [
        str(path.relative_to(repo_root))
        for path in skill_paths
        if required_text not in path.read_text(encoding="utf-8")
    ]

    assert not violations


def test_finjuice_skills_preflight_specific_capabilities_before_suggesting_commands() -> None:
    """Skill-specific CLI paths should be gated before instructions recommend them."""
    repo_root = _repo_root()
    review_skill = (repo_root / "skills/finjuice-review/SKILL.md").read_text(encoding="utf-8")

    assert "--require-capability tag.edit" in review_skill
    assert review_skill.index("--require-capability tag.edit") < review_skill.index(
        "finjuice tag --edit"
    )

    for required in (
        '--require-command "show"',
        '--require-command "explain"',
        '--require-command "rules add"',
        '--require-command "tag"',
        '--require-flag "show:--json"',
        '--require-flag "show:--untagged"',
        '--require-flag "show:--limit"',
        '--require-flag "explain:--json"',
        '--require-flag "rules add:--dry-run"',
        '--require-flag "rules add:--json"',
        '--require-flag "tag:--json"',
    ):
        assert required in review_skill

    last_preflight_check = review_skill.index("--require-capability tag.edit")
    for command in (
        "finjuice show --json --untagged --limit 50",
        'finjuice explain "merchant" --json',
        "finjuice rules add --dry-run",
        "finjuice tag --json",
    ):
        assert last_preflight_check < review_skill.index(command)


def test_finjuice_skills_do_not_use_sibling_runtime_helper_path() -> None:
    """Skill command examples should work from the workspace root used by agents."""
    repo_root = _repo_root()
    skill_paths = sorted((repo_root / "skills").glob("finjuice*/SKILL.md"))
    sibling_helper = "../finjuice/scripts/ensure_finjuice_cli.sh"

    assert skill_paths

    stale_references = [
        str(path.relative_to(repo_root))
        for path in skill_paths
        if sibling_helper in path.read_text(encoding="utf-8")
    ]

    assert not stale_references


def test_setup_guides_are_skill_first_with_runtime_ensure_after() -> None:
    """Public setup docs should lead with skills and keep CLI install as runtime ensure."""
    repo_root = _repo_root()
    default_skill_install = (
        "npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'"
    )
    runtime_install = "uv tool install git+https://github.com/sungjunlee/finjuice"
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert default_skill_install in readme
    assert runtime_install in readme
    assert readme.index(default_skill_install) < readme.index(runtime_install)

    docs = [
        repo_root / "README.md",
        repo_root / "docs/guides/setup/ai-agent-setup.md",
        repo_root / "docs/guides/setup/ai-cli-setup.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert default_skill_install in text
        assert runtime_install in text
        assert text.index(default_skill_install) < text.index(runtime_install)

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "uvx" not in text or "one-shot" in text or "fallback" in text
        assert "Homebrew" not in text or "not the recommended" in text or "추천하지" in text


def test_finjuice_curate_is_preview_first_for_rule_writes() -> None:
    """Rule curation should preview writes before mutating rules.yaml."""
    repo_root = _repo_root()
    curate_skill = (repo_root / "skills/finjuice-curate/SKILL.md").read_text(encoding="utf-8")
    protocol = (repo_root / "skills/finjuice/references/rule-decision-protocol.md").read_text(
        encoding="utf-8"
    )

    for text in (curate_skill, protocol):
        assert "--dry-run" in text
        assert "confirmation" in text or "확인" in text

    assert "Preview clear-rule writes" in curate_skill
    assert "rules add --dry-run" in curate_skill


def test_finjuice_curate_external_lookup_privacy_guardrails() -> None:
    """Merchant web lookup should stay local-first and privacy-preserving."""
    repo_root = _repo_root()
    curate_skill = (repo_root / "skills/finjuice-curate/SKILL.md").read_text(encoding="utf-8")
    protocol = (repo_root / "skills/finjuice/references/rule-decision-protocol.md").read_text(
        encoding="utf-8"
    )

    curate_guardrail = curate_skill.split(
        "- When investigating a merchant, follow the External Merchant Lookup Privacy guardrail"
    )[1]
    protocol_guardrail = protocol.split("## External Merchant Lookup Privacy")[1].split(
        "\n## Verification"
    )[0]
    required_text = [
        "local transaction pattern analysis",
        "finjuice query",
        "finjuice explain",
        "redacted/generalized",
        "raw merchant strings",
        "transaction amounts",
        "dates",
        "account names",
        "memo text",
        "raw transaction rows",
        "local file paths",
        "unique combinations of financial details",
    ]

    assert "External Merchant Lookup Privacy" in curate_skill
    assert "External Merchant Lookup Privacy" in protocol
    assert "External lookup is allowed only after user confirmation" in curate_guardrail
    assert "explicitly confirms the external lookup after seeing what will be searched" in (
        protocol_guardrail
    )

    for text in (curate_guardrail, protocol_guardrail):
        for required in required_text:
            assert required in text


def test_public_skill_surface_stays_focused_on_core_workflows() -> None:
    """Public skills should not expose premature lifecycle or tax workflows."""
    repo_root = _repo_root()
    base_skill = (repo_root / "skills/finjuice/SKILL.md").read_text(encoding="utf-8")
    review_skill = (repo_root / "skills/finjuice-review/SKILL.md").read_text(encoding="utf-8")
    report_skill = (repo_root / "skills/finjuice-report/SKILL.md").read_text(encoding="utf-8")
    report_recipes = (repo_root / "skills/finjuice-report/references/report-recipes.md").read_text(
        encoding="utf-8"
    )

    removed_terms = (
        "finjuice-tax-headroom",
        "../finjuice-tax-headroom/SKILL.md",
        "finjuice-lifecycle-plan",
        "../finjuice-lifecycle-plan/SKILL.md",
        "tax-headroom",
        "tax deduction headroom report",
        "finjuice export --format " + "tax-" + "deduction-" + "headroom",
    )

    for text in (base_skill, review_skill, report_skill, report_recipes):
        for removed_term in removed_terms:
            assert removed_term not in text


def test_finjuice_skill_side_effect_modes_are_explicit() -> None:
    """Side-effect modes should be visible in each saved-output workflow."""
    repo_root = _repo_root()
    persistence_policy = (repo_root / "skills/finjuice/references/persistence-policy.md").read_text(
        encoding="utf-8"
    )

    skill_expectations = {
        "skills/finjuice-review/SKILL.md": {"mutating-with-confirmation", "artifact-writing"},
        "skills/finjuice-report/SKILL.md": {"artifact-writing"},
        "skills/finjuice-diagnose/SKILL.md": {"journal-writing", "artifact-writing"},
        "skills/finjuice-rule-cleanup/SKILL.md": {
            "mutating-with-confirmation",
            "journal-writing",
        },
    }

    for path, expected_modes in skill_expectations.items():
        text = (repo_root / path).read_text(encoding="utf-8")
        match = re.search(r"(?ms)^## Side Effects\n(?P<body>.*?)(?=^## |\Z)", text)
        assert match
        modes_line = next(
            line for line in match.group("body").splitlines() if line.startswith("- Modes:")
        )
        declared_modes = set(re.findall(r"`([^`]+)`", modes_line))

        assert expected_modes <= declared_modes
        for mode in expected_modes:
            assert f"`{mode}`" in persistence_policy


def test_advanced_finjuice_journal_workflows_are_confirmation_first() -> None:
    """Diagnosis should not write journals by default."""
    repo_root = _repo_root()
    diagnose = (repo_root / "skills/finjuice-diagnose/SKILL.md").read_text(encoding="utf-8")

    assert "Default output is chat-only" in diagnose
    assert "only when the user asks to save" in diagnose
    assert "Persist the session outcome only after explicit consent" in diagnose
    preflight = _runtime_preflight_block(diagnose)
    assert '--require-command "journal new"' not in preflight
    assert "verify `journal new` is available" in diagnose
    assert "by default unless the user asks for chat-only output" not in diagnose


def test_finjuice_non_report_skills_define_final_response_contracts() -> None:
    """Non-report workflow skills should finish without response-shape guesswork."""
    repo_root = _repo_root()
    target_skills = [
        repo_root / "skills/finjuice-diagnose/SKILL.md",
        repo_root / "skills/finjuice-review/SKILL.md",
        repo_root / "skills/finjuice-curate/SKILL.md",
        repo_root / "skills/finjuice-rule-cleanup/SKILL.md",
    ]
    required_fields = [
        "evidence_commands",
        "mutations_applied",
        "files_written",
        "skipped_steps",
        "residual_risk",
        "next_suggested_action",
    ]

    reference = (repo_root / "skills/finjuice/references/final-response-contract.md").read_text(
        encoding="utf-8"
    )

    for field in required_fields:
        assert f"`{field}`" in reference
    assert "Korean-first" in reference

    for path in target_skills:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"(?ms)^## Final Response Contract\n(?P<body>.*?)(?=^## |\Z)", text)
        assert match, f"missing final response contract in {path.relative_to(repo_root)}"
        block = match.group("body")
        assert "final-response-contract.md" in block
        assert "Korean-first" in block
        for field in required_fields:
            assert f"`{field}`" in block, f"{path.relative_to(repo_root)} missing {field}"


def test_finjuice_report_dogfood_doc_covers_artifact_review_contract() -> None:
    """Dogfood docs should be runnable without guessing paths, prompts, or review criteria."""
    repo_root = _repo_root()
    dogfood_path = repo_root / "docs/workflows/ai-finance-report-dogfood.md"
    dogfood_doc = dogfood_path.read_text(encoding="utf-8")
    report_skill = (repo_root / "skills/finjuice-report/SKILL.md").read_text(encoding="utf-8")

    assert str(dogfood_path.relative_to(repo_root)) in report_skill

    for prompt in (
        "이번 달 소비 리포트 HTML로 만들어줘",
        "2025년 연간 소비 recap 만들어줘",
        "최근 카페/외식 지출이 왜 늘었는지 분석해서 리포트로 정리해줘",
        "리포트 만들기 전에 태깅 상태가 충분한지 먼저 봐줘",
    ):
        assert prompt in dogfood_doc

    for required_text in (
        "finjuice status --json --detailed",
        "finjuice doctor --json",
        "fixed reports",
        "agent-recombinable local reports",
        "LGTM Checklist",
        "evidence.json",
        "commands.txt",
        "report.md",
        "index.html",
        "`finjuice-report`",
        "inline `SKILL.md` fallback",
    ):
        assert required_text in dogfood_doc


def test_ai_enrichment_proposal_log_contract_is_documented() -> None:
    """AI enrichment docs should keep proposal generation separate from applying tags_ai."""
    repo_root = _repo_root()
    adr_path = repo_root / "docs/architecture/decisions/0010-ai-enrichment-proposal-log.md"
    decision_index = (repo_root / "docs/architecture/decisions/README.md").read_text(
        encoding="utf-8"
    )
    adr = adr_path.read_text(encoding="utf-8")

    assert "0010-ai-enrichment-proposal-log.md" in decision_index

    for required_text in (
        "metadata/enrichments/",
        "append-only",
        "JSONL",
        "`row_hash`",
        "`proposed_category`",
        "`proposed_tags`",
        "`rationale`",
        "`model`",
        "`provider`",
        "`prompt_version`",
        "`confidence`",
        "`created_at`",
        "`approval_state`",
        "`applied_state`",
        "only after that rewrite succeeds",
        "`proposal.apply_failed`",
        "explicit user-approved action",
        "never mutates transaction CSV partitions",
        "never silently populates `tags_ai`",
        "direct LLM writes to `tags_ai`",
        "no raw transaction rows",
        "no account numbers",
        "no sensitive free text",
        "local-first",
        "schema v4",
        "MCP/server",
        "dashboard",
        "materialized cache",
        "LLM calls inside finjuice CLI",
        "public Python API facade",
    ):
        assert required_text in adr

    assert "before or with the write" not in adr


def test_architecture_decision_index_active_count_matches_list() -> None:
    """ADR index should keep the active ADR count aligned with the numbered list."""
    repo_root = _repo_root()
    decision_index = (repo_root / "docs/architecture/decisions/README.md").read_text(
        encoding="utf-8"
    )
    active_section = decision_index.split("## Active ADRs", maxsplit=1)[1].split(
        "\n## ", maxsplit=1
    )[0]

    count_match = re.search(r"All (?P<count>\d+) current ADRs are", active_section)
    assert count_match

    active_items = re.findall(r"(?m)^\d+\. \*\*", active_section)
    assert int(count_match.group("count")) == len(active_items)


def test_index_retrieval_deferral_adr_is_documented() -> None:
    """Index ADR should document why MCP and vector search are deferred."""
    repo_root = _repo_root()
    adr_path = (
        repo_root / "docs/architecture/decisions/0011-defer-mcp-and-vector-search-for-index.md"
    )
    decision_index = (repo_root / "docs/architecture/decisions/README.md").read_text(
        encoding="utf-8"
    )
    adr = adr_path.read_text(encoding="utf-8")

    assert "0011-defer-mcp-and-vector-search-for-index.md" in decision_index

    for required_text in (
        "Catalog first, retrieval later, MCP last",
        "QMD",
        "structured finance workspace",
        "Reconsideration Triggers",
        "privacy-preserving retrieval test harness",
        "MCP tools can be generated from existing manifest/schema metadata",
        "index --json",
        "manifest --json",
    ):
        assert required_text in adr
