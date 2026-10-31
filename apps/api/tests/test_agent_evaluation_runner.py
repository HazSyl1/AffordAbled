from scripts.run_agent_evaluations import (
    CheckResult,
    _describe_case,
    _render_markdown,
)


def test_live_case_documentation_explains_workflow_and_checks() -> None:
    documentation = _describe_case(
        "Live Azure end-to-end workflows and database invariants",
        "test_live_one_turn_expense_and_split_are_saved_once_and_reported_coherently",
    )

    assert "same-turn expense" in documentation.what_it_is
    assert "₹1,608" in documentation.what_happens
    assert "₹402" in documentation.what_it_checks


def test_golden_case_documentation_uses_fixture_kind() -> None:
    documentation = _describe_case(
        "Agent goldens and exact financial outcomes",
        "test_agent_regression_golden[quantity_split_reconciles_in_paise]",
    )

    assert "Quantity split reconciles in paise" in documentation.what_it_is
    assert "per-person quantities" in documentation.what_happens
    assert "reconcile" in documentation.what_it_checks


def test_markdown_summary_contains_complete_per_case_explanation() -> None:
    result = CheckResult(
        name="Live Azure end-to-end workflows and database invariants",
        duration_seconds=1.25,
        passed=1,
        cases=[
            (
                "PASS",
                "test_live_salary_chat_records_one_verified_transaction",
            )
        ],
    )

    markdown = _render_markdown([result], live_included=True)

    assert "# AffordAbled DeepEval summary" in markdown
    assert "### PASS: `test_live_salary_chat_records_one_verified_transaction`" in markdown
    assert "**What it is:**" in markdown
    assert "**What happens:**" in markdown
    assert "**What it checks:**" in markdown
    assert "Live Azure workflows: **included**" in markdown
