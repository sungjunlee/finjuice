"""Data directory existence, permission, and structure doctor checks."""

from __future__ import annotations

import logging

from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.models import CheckResult

logger = logging.getLogger(__name__)


def _check_data_directory(config: Config) -> list[CheckResult]:
    """Check data directory status."""
    results = []
    data_dir = config.data_dir

    # Check existence
    if data_dir.exists():
        results.append(
            CheckResult(
                status="ok",
                message=f"위치: {data_dir}",
                name="data_directory_path",
            )
        )
        results.append(
            CheckResult(status="ok", message="디렉토리 존재", name="data_directory_exists")
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message=f"위치: {data_dir}",
                detail="디렉토리가 존재하지 않음",
                suggestion="finjuice import 실행 권장",
                name="data_directory_path",
            )
        )
        return results

    # Check write permission with path traversal protection
    try:
        data_dir_resolved = data_dir.resolve()
        test_file = data_dir / ".doctor_test"
        test_file_resolved = test_file.resolve()

        # Validate path is within data_dir (prevent path traversal)
        if not test_file_resolved.is_relative_to(data_dir_resolved):
            logger.warning(f"Path traversal attempt blocked: {test_file}")
            results.append(
                CheckResult(
                    status="error",
                    message="잘못된 경로",
                    detail="경로 검증 실패",
                    name="data_directory_write_access",
                )
            )
            return results

        test_file.touch()
        test_file.unlink()
        results.append(
            CheckResult(status="ok", message="쓰기 권한 확인", name="data_directory_write_access")
        )
    except PermissionError:
        results.append(
            CheckResult(
                status="error",
                message="쓰기 권한 없음",
                detail="데이터 디렉토리에 쓰기 권한이 없습니다",
                suggestion=f"chmod u+w {data_dir}",
                name="data_directory_write_access",
            )
        )
    except OSError as e:
        results.append(
            CheckResult(
                status="warning",
                message="권한 확인 실패",
                detail=str(e),
                name="data_directory_write_access",
            )
        )

    # Check subdirectories
    subdirs = ["imports", "transactions", "exports", "metadata"]
    missing_subdirs = []
    for subdir in subdirs:
        if not (data_dir / subdir).exists():
            missing_subdirs.append(subdir)

    if missing_subdirs:
        results.append(
            CheckResult(
                status="warning",
                message=f"누락된 디렉토리: {', '.join(missing_subdirs)}",
                suggestion="finjuice import 실행 권장",
                name="data_directory_structure",
            )
        )

    return results
