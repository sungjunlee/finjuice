"""Transfer detection command for finjuice CLI.

Detects and pairs internal transfers in CSV partitions.
Split from pipeline.py as part of Issue #269.
"""

import logging
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def _compute_transfer(config: Any) -> dict[str, Any]:
    """Compute transfer detection summary."""
    from finjuice.pipeline.transfer.detection import run_transfer_detection

    logger.info("Running transfer detection...")
    result = run_transfer_detection(config.csv_base_dir)

    return {
        "status": "ok",
        "candidate_rows": int(result.get("candidate_rows", result.get("candidates", 0))),
        "candidates_considered": int(result.get("candidates", 0)),
        "pairs_found": int(result.get("pairs", 0)),
        "pairs_linked": int(result.get("paired", 0)),
        "confirmed_transfer_rows": int(result.get("confirmed", result.get("paired", 0))),
        "unconfirmed_candidate_rows": int(result.get("unconfirmed_candidates", 0)),
    }


def _render_transfer(result: dict[str, Any]) -> None:
    """Render human-readable transfer summary."""
    output.success("[OK] Transfer detection complete:")
    output.info(f"  Transfer candidates: {result['candidate_rows']}")
    output.info(f"  Transfers detected: {result['pairs_found']}")
    output.info(f"  Confirmed transfer rows: {result['confirmed_transfer_rows']}")
    output.info(f"  Unconfirmed candidate rows: {result['unconfirmed_candidate_rows']}")


def transfer_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Detect and pair internal transfers.

    Identifies transfer pairs by matching amounts and time windows (±5 minutes).
    Sets is_transfer_candidate=1 for transfer-like rows, then sets is_transfer=1
    and assigns transfer_group_id only for confirmed paired transactions.

    Note: This is automatically called by 'finjuice refresh'.
    """
    config = get_config(ctx)

    try:
        result = _compute_transfer(config)
        emit(result, json_output, _render_transfer, command="transfer")

    except typer.Exit:
        raise  # Re-raise typer.Exit without modification
    except (ValueError, RuntimeError) as e:
        logger.error(f"Transfer detection failed: {e}", exc_info=True)
        emit_error(
            f"Transfer detection failed: {e}",
            error_code=ErrorCode.TRANSFER_FAILED,
            json_output=json_output,
            command="transfer",
        )
    except KeyboardInterrupt:
        emit_error(
            "Transfer detection cancelled by user.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command="transfer",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(
            f"Unexpected error during transfer detection: {type(e).__name__}: {e}", exc_info=True
        )
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="transfer",
        )
