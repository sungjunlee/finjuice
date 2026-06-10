"""Focused tests for goals.yaml validator contracts."""

from finjuice.pipeline.goals_validators import GoalsDocument, validate_goals_payload


def test_validate_goals_payload_reports_malformed_required_sections() -> None:
    """Malformed required sections should preserve existing validation messages."""
    payload = {
        "version": "1",
        "monthly_budget": {
            "total": True,
            "categories": {"food": -1, "": 1000},
            "updated": "2026-02-30",
            "notes": ["private"],
        },
    }

    document, problems = validate_goals_payload(payload)

    assert document is None
    assert [(problem.path, problem.message) for problem in problems] == [
        ("version", "must be integer 1"),
        ("monthly_budget.total", "must be a non-negative integer"),
        ("monthly_budget.categories.food", "must be a non-negative integer"),
        ("monthly_budget.categories", "category names must be non-empty strings"),
        (
            "monthly_budget.updated",
            "must be a real calendar date in YYYY-MM-DD format",
        ),
        ("monthly_budget.notes", "must be a string"),
    ]


def test_validate_goals_payload_accepts_partial_optional_sections() -> None:
    """Optional goals sections may be omitted while present sub-sections validate."""
    payload = {
        "version": 1,
        "monthly_budget": {"total": 0, "categories": {}},
        "financial_context": {
            "income": {
                "monthly_estimate": 0,
                "as_of": "2026-05-01",
            }
        },
    }

    document, problems = validate_goals_payload(payload)

    assert problems == []
    assert isinstance(document, GoalsDocument)
    assert document.monthly_budget.total == 0
    assert document.recurring_savings == []
    assert document.known_obligations == []
    assert document.financial_context is not None
    assert document.financial_context.income is not None
    assert document.financial_context.income.monthly_estimate == 0
    assert document.financial_context.family is None
    assert document.financial_context.housing is None


def test_validate_goals_payload_accepts_zero_amounts_and_far_future_dates() -> None:
    """Boundary goal amounts and lifecycle dates should stay valid."""
    payload = {
        "version": 1,
        "monthly_budget": {
            "total": 0,
            "categories": {"housing": 0},
            "updated": "2099-12-31",
        },
        "net_worth_target": 0,
        "recurring_savings": [
            {
                "label": "Pause savings",
                "amount": 0,
                "frequency": "monthly",
                "start_month": "2099-12",
                "end_month": "2099-12",
                "start_date": "2099-12-01",
                "end_date": "2099-12-31",
            }
        ],
        "known_obligations": [
            {
                "label": "Temporary obligation",
                "amount": 0,
                "frequency": "yearly",
                "start_month": "2099-01",
                "end_month": "2099-12",
            }
        ],
    }

    document, problems = validate_goals_payload(payload)

    assert problems == []
    assert document is not None
    assert document.net_worth_target == 0
    assert document.recurring_savings is not None
    assert document.recurring_savings[0].amount == 0
    assert document.recurring_savings[0].end_date == "2099-12-31"
    assert document.known_obligations is not None
    assert document.known_obligations[0].amount == 0
