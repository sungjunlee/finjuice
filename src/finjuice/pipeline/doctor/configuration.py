"""Configuration doctor checks for rules.yaml and environment variables."""

from __future__ import annotations

import logging
import os

from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.models import CheckResult
from finjuice.pipeline.tagging.rules_yaml_io import load_rules
from finjuice.pipeline.tagging.validator import validate_rules

logger = logging.getLogger(__name__)


def _check_configuration(config: Config) -> list[CheckResult]:
    """Check configuration status."""
    results = []

    # Check rules.yaml
    rules_path = config.rules_file
    if rules_path.exists():
        try:
            import yaml

            with open(rules_path, encoding="utf-8") as f:
                rules_data = yaml.safe_load(f)

            rule_count = 0
            if rules_data and "rules" in rules_data:
                rule_count = len(rules_data["rules"])

            results.append(
                CheckResult(
                    status="ok",
                    message=f"rules.yaml: {rule_count}개 규칙",
                    name="rules_file",
                )
            )

            # Check for rule conflicts using the full validation engine
            if rule_count > 0:
                try:
                    tag_rules = load_rules(rules_path)
                    validation = validate_rules(tag_rules)
                    real_issues = [
                        i for i in validation.issues if i.severity in ("error", "warning")
                    ]
                    if real_issues:
                        overlap_count = sum(
                            1 for i in real_issues if i.issue_type == "pattern_overlap"
                        )
                        inversion_count = sum(
                            1 for i in real_issues if i.issue_type == "priority_inversion"
                        )
                        parts = []
                        if overlap_count:
                            parts.append(f"패턴 중복 {overlap_count}건")
                        if inversion_count:
                            parts.append(f"우선순위 역전 {inversion_count}건")
                        details = ", ".join(parts) if parts else "검증 이슈 발생"
                        results.append(
                            CheckResult(
                                status="warning",
                                message=f"규칙 충돌: {details}",
                                suggestion="finjuice rules validate 실행 권장",
                                name="rule_priority_conflicts",
                            )
                        )
                except (ValueError, RuntimeError):
                    logger.warning("규칙 검증 중 오류 (rules_path=%s)", rules_path, exc_info=True)

        except yaml.YAMLError as e:
            # Sanitize error message to avoid exposing file contents
            error_mark = getattr(e, "problem_mark", None)
            if error_mark:
                safe_detail = f"Line {error_mark.line + 1}, column {error_mark.column + 1}"
            else:
                safe_detail = "YAML 문법 오류"
            results.append(
                CheckResult(
                    status="error",
                    message="rules.yaml 파싱 오류",
                    detail=safe_detail,
                    suggestion="YAML 문법 오류 수정 필요",
                    name="rules_file_parse",
                )
            )
        except (OSError, TypeError, AttributeError) as e:
            results.append(
                CheckResult(
                    status="warning",
                    message="rules.yaml 읽기 실패",
                    detail=str(e),
                    name="rules_file_read",
                )
            )
    else:
        results.append(
            CheckResult(
                status="warning",
                message="rules.yaml 없음",
                suggestion="finjuice import 실행 권장",
                name="rules_file",
            )
        )

    # Check environment variables
    env_var = os.getenv("FINJUICE_DATA_DIR")
    if env_var:
        results.append(
            CheckResult(
                status="ok",
                message=f"FINJUICE_DATA_DIR: {env_var}",
                name="env_finjuice_data_dir",
            )
        )

    return results
