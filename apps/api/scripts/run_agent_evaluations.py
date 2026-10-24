"""Run all AffordAbled DeepEval checks and print one actionable summary."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AffordAbled DeepEval checks with one summary")
    parser.add_argument("--live", action="store_true", help="Also call the Azure model using an isolated test database")
    parser.add_argument(
        "--live-only", action="store_true",
        help="Run only the paid Azure end-to-end cases using an isolated test database",
    )
    parser.add_argument("--verbose", action="store_true", help="Show every passing test as well as failures")
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
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
