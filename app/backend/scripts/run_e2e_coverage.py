from __future__ import annotations

import argparse
from pathlib import Path

from backend.automation.fill_form import fill_form
from backend.config import resolve_form_url
from backend.main import (
    _create_run_dir,
    _log_run,
    _write_final_snapshot,
    _write_json_artifact,
    _write_result,
    _write_text_artifact,
    extract_documents_with_text,
)
from backend.pipeline.coverage_report import build_e2e_coverage_report
from backend.pipeline.post_autofill import validate_post_autofill
from backend.pipeline.validate import validate_and_annotate


def _fixture_form_uri() -> str:
    fixtures_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    form_path = fixtures_dir / "form.html"
    if not form_path.exists():
        raise FileNotFoundError(f"Local form fixture missing: {form_path}")
    return form_path.resolve().as_uri()


def _run_once(passport_path: Path, g28_path: Path, form_url: str) -> str:
    run_dir = _create_run_dir()
    _log_run(run_dir, "E2E coverage run started")

    result, passport_text, g28_text = extract_documents_with_text(
        passport_path=passport_path,
        g28_path=g28_path,
        use_llm_extract=False,
        run_dir=run_dir,
    )
    _write_text_artifact(run_dir, "passport_ocr.txt", passport_text)
    _write_text_artifact(run_dir, "g28_ocr.txt", g28_text)
    validate_and_annotate(result, use_llm=False)
    _write_result(run_dir, result)

    summary = fill_form(
        result.model_dump(),
        run_dir,
        form_url=form_url,
        headless=True,
        keep_open_ms=0,
    )
    _write_json_artifact(run_dir, "autofill_summary.json", summary)

    report, llm_error, updated = validate_post_autofill(
        result,
        summary,
        passport_text,
        g28_text,
        use_llm=True,
    )
    report_payload = dict(report)
    if llm_error:
        report_payload["llm_error"] = llm_error
    _write_json_artifact(run_dir, "post_autofill_validation.json", report_payload)
    _write_final_snapshot(run_dir, run_dir.name, updated, summary, report_payload)

    coverage = build_e2e_coverage_report(
        run_id=run_dir.name,
        result=updated,
        autofill_report=summary,
        validation_report=report_payload,
    )
    _write_json_artifact(run_dir, "e2e_coverage_report.json", coverage)
    _log_run(run_dir, "E2E coverage run complete")
    return run_dir.name


def main() -> None:
    parser = argparse.ArgumentParser(description="Run end-to-end coverage pipeline on fixtures.")
    parser.add_argument("--passport", type=Path, required=True, help="Path to passport fixture")
    parser.add_argument("--g28", type=Path, required=True, help="Path to G-28 fixture")
    parser.add_argument(
        "--form-url",
        type=str,
        default=None,
        help="Override form URL (defaults to local fixture)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Also run a smoke autofill against the configured real form URL",
    )
    args = parser.parse_args()

    fixture_url = args.form_url or _fixture_form_uri()
    run_id = _run_once(args.passport, args.g28, fixture_url)
    print(f"Fixture run complete: {run_id}")

    if args.smoke:
        real_url = resolve_form_url(None)
        smoke_run_id = _run_once(args.passport, args.g28, real_url)
        print(f"Smoke run complete: {smoke_run_id}")


if __name__ == "__main__":
    main()
