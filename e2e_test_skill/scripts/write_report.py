"""Render the E2E run summary (JSON on stdin) into a Markdown report.

Invoked by SKILL.md step 4. Writes to reports/run-<timestamp>.md and prints
the path so the skill can surface it to the user.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
REPORTS = REPO_DIR / "reports"


def main():
    data = json.load(sys.stdin)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = REPORTS / f"run-{ts}.md"
    REPORTS.mkdir(exist_ok=True)

    verdict = "PASS" if data["failed"] == 0 else "FAIL"
    lines = [
        f"# E2E Checkout Run — {verdict}",
        "",
        f"- **Timestamp:** {ts}",
        f"- **Test user:** `{data['test_user']}`",
        f"- **Order ID:** `{data.get('order_id') or 'n/a'}`",
        f"- **Passed:** {data['passed']} / **Failed:** {data['failed']}",
        f"- **Wall time:** {data['total_ms']} ms",
        "",
        "| Step | Result | Time |",
        "|---|---|---|",
    ]
    for s in data["steps"]:
        mark = "✅" if s["ok"] else "❌"
        detail = "" if s["ok"] else f" — `{s.get('error', '')}`"
        lines.append(f"| `{s['step']}` | {mark}{detail} | {s['ms']} ms |")
    lines.append("")

    path.write_text("\n".join(lines))
    print(str(path.relative_to(REPO_DIR)))


if __name__ == "__main__":
    main()
