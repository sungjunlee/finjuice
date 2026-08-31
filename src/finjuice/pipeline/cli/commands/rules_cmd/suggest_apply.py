"""Interactive apply flow for ``finjuice rules suggest``.

Owns the suggestion review loop, auto-apply, and optional re-tagging.
The Typer command and JSON payloads stay in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.suggest`, which re-exports
the apply helper so existing callers can keep importing from that module.
"""

from __future__ import annotations

import typer

from finjuice.pipeline.config import Config

from .shared import _append_rule_mutation_audit_event


def _interactive_apply_suggestions(
    suggestions: list,
    config: Config,
    yes: bool,
    tag_after: bool,
    before_coverage: float,
    total_count: int,
) -> None:
    """
    Interactively prompt user to apply suggested rules.

    Args:
        suggestions: List of merchant context suggestion dictionaries
        config: CLI config with paths
        yes: If True, apply all without prompts
        tag_after: If True, re-tag after applying
        before_coverage: Coverage percentage before applying
        total_count: Total transaction count
    """
    from finjuice.pipeline.tagging.pipeline import run_tagging
    from finjuice.pipeline.tagging.suggestions import (
        apply_suggestion_to_rules,
        build_rule_dict_from_suggestion,
        is_auto_apply_eligible,
    )

    applied_count = 0
    skipped_count = 0

    typer.echo(f"📋 {len(suggestions)}개의 규칙 제안을 검토합니다.\n")
    typer.echo("  [y] 적용  [n] 건너뛰기  [e] 태그 편집  [s] 나머지 모두 건너뛰기  [q] 종료\n")

    for i, suggestion in enumerate(suggestions, 1):
        default_rule = build_rule_dict_from_suggestion(suggestion)

        # Display suggestion
        typer.echo(f"[{i}/{len(suggestions)}] {suggestion['merchant']}")
        typer.echo(
            f"     거래: {int(suggestion['transaction_count'])}건, "
            f"₩{float(suggestion['total_amount']):,.0f}"
        )
        typer.echo(f'     패턴: "{suggestion["pattern"]}"')
        typer.echo(f"     카테고리: {default_rule.get('category') or '미분류'}")
        typer.echo(f"     기본 태그: {default_rule['tags']}")
        if not is_auto_apply_eligible(suggestion):
            typer.echo("     권장: 규칙 생성 비추천 (payment_gateway)")

        if yes:
            if not is_auto_apply_eligible(suggestion):
                typer.echo("     - auto-apply 제외됨\n")
                skipped_count += 1
                continue
            # Auto mode: apply without prompting
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo("     ✓ 규칙 추가됨\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1
            continue

        # Interactive mode
        try:
            response = (
                typer.prompt(
                    "     적용?",
                    default="n",
                    show_default=True,
                )
                .lower()
                .strip()
            )
        except (EOFError, KeyboardInterrupt):
            typer.echo("\n⚠️  중단됨.", err=True)
            break

        if response == "y":
            # Apply as-is
            try:
                applied_rule = apply_suggestion_to_rules(suggestion, config.rules_file)
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo("     ✓ 규칙 추가됨\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1

        elif response == "e":
            # Edit tags
            tags_input = typer.prompt(
                "     태그 수정 (쉼표 구분)",
                default=", ".join(default_rule["tags"]),
            )
            modified_tags = [t.strip() for t in tags_input.split(",") if t.strip()]

            if not modified_tags:
                typer.echo("     ✗ 태그가 비어있습니다. 건너뜁니다.\n")
                skipped_count += 1
                continue

            try:
                applied_rule = apply_suggestion_to_rules(
                    suggestion, config.rules_file, modified_tags=modified_tags
                )
                _append_rule_mutation_audit_event(
                    config,
                    command="rules suggest",
                    action="applied",
                    rule_name=applied_rule.name,
                    change_summary="suggestion rule applied",
                )
                typer.echo(f"     ✓ 규칙 추가됨 (태그: {modified_tags})\n")
                applied_count += 1
            except (OSError, ValueError) as e:
                typer.echo(f"     ✗ 실패: {e}\n", err=True)
                skipped_count += 1

        elif response == "s":
            # Skip all remaining
            remaining = len(suggestions) - i
            typer.echo(f"     ℹ️  나머지 {remaining}개 건너뜁니다.\n")
            skipped_count += remaining
            break

        elif response == "q":
            # Quit
            typer.echo("\n⚠️  종료합니다.")
            break

        else:
            # n or anything else: skip this one
            typer.echo("     - 건너뜀\n")
            skipped_count += 1

    # Summary
    typer.echo("─" * 50)
    typer.echo(f"📊 결과: {applied_count}개 적용, {skipped_count}개 건너뜀")

    if applied_count == 0:
        typer.echo("\nℹ️  적용된 규칙이 없습니다.")
        return

    # Re-tag if requested
    if tag_after:
        typer.echo("\n🔄 트랜잭션 재태깅 중...")
        try:
            result = run_tagging(
                csv_base_dir=config.csv_base_dir,
                rules_path=config.rules_file,
                dry_run=False,
            )
            after_coverage = result.get("coverage_pct", 0)

            typer.echo("\n📈 커버리지 변화:")
            typer.echo(f"   이전: {before_coverage:.1f}%")
            typer.echo(f"   이후: {after_coverage:.1f}%")
            typer.echo(f"   개선: +{after_coverage - before_coverage:.1f}%p")

        except (ValueError, KeyError, OSError) as e:
            typer.echo(f"\n⚠️  재태깅 실패: {e}", err=True)
            typer.echo("수동으로 'finjuice tag'를 실행하세요.")
    else:
        typer.echo("\n💡 재태깅을 위해 'finjuice tag'를 실행하세요.")
