"""Run all AffordAbled DeepEval checks and print one actionable summary."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_FILE = API_ROOT / ".deepeval" / "summary.md"
GOLDENS_FILE = API_ROOT / "tests" / "goldens" / "agent_regressions.json"


@dataclass(frozen=True)
class CaseDocumentation:
    what_it_is: str
    what_happens: str
    what_it_checks: str


GROUP_DOCUMENTATION = {
    "Agent goldens and exact financial outcomes": CaseDocumentation(
        "Deterministic financial and orchestration regression fixtures.",
        "Runs trusted calculators and task-evidence helpers without calling an LLM or database.",
        "Exact structured results, paise reconciliation, verified IDs, date windows, and memory candidates.",
    ),
    "Guardrail decisions": CaseDocumentation(
        "Safety routing examples for allowed and blocked finance messages.",
        "Classifies each fixed prompt through the configured guardrail evaluator.",
        "The resulting allow, block, or refusal label matches the expected policy decision.",
    ),
    "Chat orchestration, task evidence, and thread history": CaseDocumentation(
        "LangGraph routing, durable task contracts, and conversation continuity tests.",
        "Exercises supervisor and specialist handoffs across new turns, resumptions, and stored threads.",
        "Tasks complete only from matching tool evidence and state survives routing and resume boundaries.",
    ),
    "Expense splits and settlement arithmetic": CaseDocumentation(
        "Expense split, IOU, and complex settlement calculation tests.",
        "Runs equal, itemized, quantity, debt, contribution, and multi-bill scenarios.",
        "Every paise reconciles, participant shares are exact, and persistence uses the correct transaction.",
    ),
    "Spending queries and date filters": CaseDocumentation(
        "Read-only transaction analytics and calendar-window tests.",
        "Resolves user date phrases and executes filtered, ordered, and limited transaction queries.",
        "Date boundaries, ordering, totals, and user scoping are correct without creating data.",
    ),
    "Memory capture and review": CaseDocumentation(
        "Memory-signal extraction, aggregation, and review workflow tests.",
        "Processes transaction edits and chat evidence into bounded memory-review candidates.",
        "Only supported preferences are proposed, duplicates merge correctly, and users remain isolated.",
    ),
    "Voice transcription handoff": CaseDocumentation(
        "Speech-to-chat boundary tests.",
        "Processes supported audio input and hands the transcription to the chat workflow.",
        "Validation, transcription output, and error handling remain stable.",
    ),
    "Live Azure end-to-end workflows and database invariants": CaseDocumentation(
        "Paid end-to-end evaluations using the configured Azure model and an isolated test database.",
        "Sends real chat messages through guardrails, supervisor, specialists, tools, and persistence.",
        "The user response agrees with authoritative database writes and exact financial invariants.",
    ),
}


LIVE_CASE_DOCUMENTATION = {
    "test_live_salary_chat_records_one_verified_transaction": CaseDocumentation(
        "A simple salary recording workflow.",
        "Creates an isolated Axis account, asks chat to record a ₹60,000 salary, then reads transactions.",
        "Exactly one ₹60,000 income exists, the graph reports completion, and the returned transaction ID "
        "is persisted.",
    ),
    "test_live_one_turn_expense_and_split_are_saved_once_and_reported_coherently": CaseDocumentation(
        "A same-turn expense and equal-split workflow.",
        "Records a ₹1,608 Masato expense and splits it among the owner, Rujul, Sudhansu, and Sujal in one request.",
        "One expense and one linked split exist, all four shares are ₹402, totals reconcile, and the response "
        "reports both actions.",
    ),
    "test_live_complex_quantity_debt_and_contribution_split_reconciles_exactly": CaseDocumentation(
        "A reviewed quantity split with an earlier contribution and cross-person debts.",
        "Records ₹927,383, prices seven drinks each for A, B, and C, divides the remainder among eight people, "
        "then confirms the review.",
        "Drink and remainder totals, shares, B's contribution, A↔C↔B debts, final transfers, confirmation "
        "state, and database linkage are exact.",
    ),
    "test_live_followup_split_links_one_expense_without_recreating_it": CaseDocumentation(
        "A split requested in a later chat turn.",
        "Records an expense first, then asks to split the previously verified transaction using the same thread.",
        "The original expense is not duplicated and exactly one split links to its authoritative transaction ID.",
    ),
    "test_live_receipt_records_one_grand_total_and_no_split": CaseDocumentation(
        "A receipt ingestion workflow with deferred split consent.",
        "Submits receipt OCR containing line items, taxes, and one final grand total.",
        "Exactly one expense uses the grand total, receipt rows do not become separate transactions, and no split "
        "is created prematurely.",
    ),
    "test_live_largest_transaction_query_reads_data_without_writing": CaseDocumentation(
        "A read-only largest-transaction analytics workflow.",
        "Seeds transactions, asks chat which transaction was largest, and reads the wallet again.",
        "The answer is grounded in the largest persisted transaction and the query creates no transaction or split.",
    ),
}


GOLDEN_KIND_DOCUMENTATION = {
    "task_completion": CaseDocumentation(
        "A task-contract evidence decision.",
        "Feeds a specialist result and its tool observations into deterministic completion verification.",
        "A mutation completes only when the required successful tool evidence and persisted ID are present.",
    ),
    "followup_transaction": CaseDocumentation(
        "A follow-up reference to an earlier transaction.",
        "Builds verified transaction references from prior successful tool observations and resolves the follow-up.",
        "Only successful, unambiguous, request-matching transaction IDs may be reused for a split.",
    ),
    "quantity_split": CaseDocumentation(
        "A quantity-based expense allocation.",
        "Prices explicit per-person quantities and divides the remaining amount deterministically.",
        "Owner and participant shares match the golden paise values and reconcile to the total.",
    ),
    "settlement_split": CaseDocumentation(
        "A deterministic settlement with quantities, contributions, and debts.",
        "Calculates expense shares and nets prior payments and IOUs into settlement transfers.",
        "Priced items, remainder, shares, and every transfer exactly match the golden fixture.",
    ),
    "itemized_split": CaseDocumentation(
        "An item-level expense allocation.",
        "Allocates priced rows to their named consumers while applying owner-inclusion rules.",
        "Shares reconcile exactly, owner defaults are respected, and incomplete bill rows are rejected.",
    ),
    "memory_candidate": CaseDocumentation(
        "A deterministic memory-review candidate extraction.",
        "Compares the before and after state of an accepted or edited finance action.",
        "The correct scoped preference is proposed and invalid owner/contact memories are omitted.",
    ),
    "date_window": CaseDocumentation(
        "A natural-language date-window calculation.",
        "Resolves relative phrases against a fixed trusted clock and timezone.",
        "UTC start and end boundaries exactly match the expected local calendar period.",
    ),
}


def _load_golden_kinds() -> dict[str, str]:
    try:
        cases = json.loads(GOLDENS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(case.get("name")): str(case.get("kind"))
        for case in cases
        if isinstance(case, dict) and case.get("name") and case.get("kind")
    }


GOLDEN_KINDS = _load_golden_kinds()


def _humanize_case_name(case_name: str) -> str:
    parameter = re.search(r"\[([^\]]+)\]$", case_name)
    raw_name = parameter.group(1) if parameter else re.sub(r"^test_", "", case_name)
    return raw_name.replace("_", " ").strip().capitalize()


def _describe_case(group_name: str, case_name: str) -> CaseDocumentation:
    if case_name in LIVE_CASE_DOCUMENTATION:
        return LIVE_CASE_DOCUMENTATION[case_name]
    parameter = re.search(r"\[([^\]]+)\]$", case_name)
    golden_name = parameter.group(1) if parameter else ""
    golden_kind = GOLDEN_KINDS.get(golden_name)
    if golden_kind in GOLDEN_KIND_DOCUMENTATION:
        base = GOLDEN_KIND_DOCUMENTATION[golden_kind]
        return CaseDocumentation(
            what_it_is=f"{_humanize_case_name(case_name)}. {base.what_it_is}",
            what_happens=base.what_happens,
            what_it_checks=base.what_it_checks,
        )
    group = GROUP_DOCUMENTATION.get(group_name)
    return CaseDocumentation(
        what_it_is=_humanize_case_name(case_name) + ".",
        what_happens=(
            group.what_happens
            if group
            else "Runs this regression scenario through its production boundary."
        ),
        what_it_checks=(group.what_it_checks if group else "All assertions and required invariants pass."),
    )


@dataclass
class CheckResult:
    name: str
    duration_seconds: float
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    cases: list[tuple[str, str]] = field(default_factory=list)
    diagnostics: str = ""
    artifact_directory: str | None = None
    exit_code: int = 0

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.passed > 0


def _run_pytest(name: str, paths: list[str], *, selection: str | None = None, live: bool = False) -> CheckResult:
    environment = os.environ.copy()
    environment["LANGSMITH_TRACING"] = "false"
    artifact_directory = None
    if live:
        environment["RUN_DEEPEVAL_LIVE"] = "1"
        artifact_directory = API_ROOT / ".deepeval-results" / time.strftime("%Y%m%d-%H%M%S")
        environment["DEEPEVAL_ARTIFACT_DIR"] = str(artifact_directory)
    command = [
        sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
        *paths, "--tb=short",
    ]
    if selection:
        command.extend(["-k", selection])
    started = time.monotonic()
    process = subprocess.run(
        command, cwd=API_ROOT, env=environment, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    result = CheckResult(
        name=name,
        duration_seconds=time.monotonic() - started,
        artifact_directory=str(artifact_directory) if artifact_directory is not None else None,
        exit_code=process.returncode,
    )
    result.diagnostics = "\n".join(part for part in (process.stdout.strip(), process.stderr.strip()) if part)
    for line in process.stdout.splitlines():
        match = re.match(r"^tests[/\\].*?::(\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)\b", line)
        if match is None:
            continue
        case_name, status = match.groups()
        result.cases.append(("PASS" if status == "PASSED" else "SKIP" if status == "SKIPPED" else "FAIL", case_name))
        if status == "PASSED":
            result.passed += 1
        elif status == "SKIPPED":
            result.skipped += 1
        else:
            result.failed += 1
    if (process.returncode or not result.cases) and not result.failed:
        result.failed = 1  # Collection or setup failed before pytest wrote a testcase.
    return result


def _run_guardrails() -> CheckResult:
    started = time.monotonic()
    process = subprocess.run(
        [sys.executable, "scripts/run_deepeval_guardrail_eval.py"],
        cwd=API_ROOT, env={**os.environ, "LANGSMITH_TRACING": "false"},
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False,
    )
    result = CheckResult(
        name="Guardrail decisions", duration_seconds=time.monotonic() - started,
        exit_code=process.returncode,
    )
    result.diagnostics = "\n".join(part for part in (process.stdout.strip(), process.stderr.strip()) if part)
    for line in process.stdout.splitlines():
        match = re.match(r"^(PASS|FAIL) ([a-z_]+)(?::|$)", line)
        if match:
            status, name = match.groups()
            result.cases.append((status, name))
            if status == "PASS":
                result.passed += 1
            else:
                result.failed += 1
    if (process.returncode or not result.cases) and not result.failed:
        result.failed = 1
    return result


def _case_detail_lines(group_name: str, case_name: str, *, indent: str = "    ") -> list[str]:
    documentation = _describe_case(group_name, case_name)
    return [
        f"{indent}What it is: {documentation.what_it_is}",
        f"{indent}What happens: {documentation.what_happens}",
        f"{indent}What it checks: {documentation.what_it_checks}",
    ]


def _render_markdown(results: list[CheckResult], *, live_included: bool) -> str:
    passed = sum(result.passed for result in results)
    failed = sum(result.failed for result in results)
    skipped = sum(result.skipped for result in results)
    duration = sum(result.duration_seconds for result in results)
    overall_ok = all(result.ok for result in results)
    lines = [
        "# AffordAbled DeepEval summary",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Overall result",
        "",
        f"- Result: **{'PASS' if overall_ok else 'FAIL'}**",
        f"- Passed: **{passed}**",
        f"- Failed: **{failed}**",
        f"- Skipped: **{skipped}**",
        f"- Duration: **{duration:.1f}s**",
        f"- Live Azure workflows: **{'included' if live_included else 'not run'}**",
    ]
    for result in results:
        group_status = "PASS" if result.ok else "FAIL"
        group_documentation = GROUP_DOCUMENTATION.get(result.name)
        lines.extend([
            "",
            f"## {group_status}: {result.name}",
            "",
            f"{result.passed} passed, {result.failed} failed, {result.skipped} skipped "
            f"in {result.duration_seconds:.1f}s.",
        ])
        if group_documentation:
            lines.extend([
                "",
                f"**Scope:** {group_documentation.what_it_is}",
                "",
                f"**Execution:** {group_documentation.what_happens}",
                "",
                f"**Coverage:** {group_documentation.what_it_checks}",
            ])
        for case_status, case_name in result.cases:
            documentation = _describe_case(result.name, case_name)
            lines.extend([
                "",
                f"### {case_status}: `{case_name}`",
                "",
                f"- **What it is:** {documentation.what_it_is}",
                f"- **What happens:** {documentation.what_happens}",
                f"- **What it checks:** {documentation.what_it_checks}",
            ])
        if not result.ok and result.diagnostics:
            lines.extend([
                "",
                "### Failure diagnostics",
                "",
                "```text",
                result.diagnostics,
                "```",
            ])
        if result.artifact_directory:
            lines.extend(["", f"Failure artifacts: `{result.artifact_directory}`"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AffordAbled DeepEval checks with one summary")
    parser.add_argument("--live", action="store_true", help="Also call the Azure model using an isolated test database")
    parser.add_argument(
        "--live-only", action="store_true",
        help="Run only the paid Azure end-to-end cases using an isolated test database",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show every case with what it is, what happens, and what it checks",
    )
    parser.add_argument(
        "--summary-file", default=str(DEFAULT_SUMMARY_FILE),
        help="Write the complete per-case Markdown report to this path",
    )
    args = parser.parse_args()

    results = []
    if not args.live_only:
        results.extend([
            _run_pytest("Agent goldens and exact financial outcomes", ["tests/test_deepeval_agent_regressions.py"],
                        selection="not live_"),
            _run_guardrails(),
            _run_pytest("Chat orchestration, task evidence, and thread history", [
                "tests/test_agentic_chat_api.py", "tests/test_agent_supervisor_graph.py",
                "tests/test_threads.py", "tests/test_intent_classifier.py",
            ]),
            _run_pytest("Expense splits and settlement arithmetic", [
                "tests/test_itemized_splits.py", "tests/test_settlement_split.py",
                "tests/test_complex_settlement.py", "tests/test_complex_settlement_api.py",
            ]),
            _run_pytest("Spending queries and date filters", ["tests/test_transaction_query_tools.py"]),
            _run_pytest("Memory capture and review", [
                "tests/test_transaction_memory_capture.py", "tests/test_chat_memory_analysis.py",
                "tests/test_shared_memory.py",
            ]),
            _run_pytest("Voice transcription handoff", ["tests/test_speech_service.py"]),
        ])
    if args.live or args.live_only:
        results.append(_run_pytest(
            "Live Azure end-to-end workflows and database invariants",
            ["tests/test_deepeval_agent_regressions.py"], selection="live_", live=True,
        ))

    print("\nAffordAbled DeepEval summary")
    print("=" * 28)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(
            f"{status}  {result.name}: {result.passed} passed, {result.failed} failed, "
            f"{result.skipped} skipped ({result.duration_seconds:.1f}s)"
        )
        for case_status, case_name in result.cases:
            if args.verbose or case_status != "PASS":
                print(f"  {case_status}  {case_name}")
                for detail_line in _case_detail_lines(result.name, case_name):
                    print(detail_line)
        if not result.ok:
            print("  Details:")
            for line in result.diagnostics.splitlines():
                print(f"    {line}")
        if result.artifact_directory:
            print(f"  Failure artifacts: {result.artifact_directory}")
    if not args.live and not args.live_only:
        print("Live Azure workflows: not run (add --live to include them)")
    passed = sum(result.passed for result in results)
    failed = sum(result.failed for result in results)
    skipped = sum(result.skipped for result in results)
    duration = sum(result.duration_seconds for result in results)
    print(f"Total: {passed} passed, {failed} failed, {skipped} skipped in {duration:.1f}s")
    print("Result: PASS" if all(result.ok for result in results) else "Result: FAIL")
    summary_path = Path(args.summary_file).expanduser()
    if not summary_path.is_absolute():
        summary_path = API_ROOT / summary_path
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        _render_markdown(results, live_included=bool(args.live or args.live_only)),
        encoding="utf-8",
    )
    print(f"Detailed Markdown summary: {summary_path}")
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
