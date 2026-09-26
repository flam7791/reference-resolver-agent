"""Outputs for people: a JSON record of everything, a review queue, and a readable summary."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .llm import UsageMeter
from .models import STATUSES, Resolution


def summary(resolutions: list[Resolution], meter: UsageMeter) -> dict:
    status = Counter(r.status for r in resolutions)
    method = Counter(r.method for r in resolutions if r.status == "linked")
    total = len(resolutions) or 1
    return {
        "references": len(resolutions),
        "by_status": {s: status.get(s, 0) for s in STATUSES},
        "linked_by_method": dict(method),
        "automation_rate": round(status.get("linked", 0) / total, 3),
        "model": meter.summary(),
        "cost_per_reference_usd": round(meter.cost_usd / total, 5),
    }


def write_outputs(resolutions: list[Resolution], meter: UsageMeter, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    facts = summary(resolutions, meter)

    (out_dir / "resolutions.json").write_text(
        json.dumps(
            {"summary": facts, "resolutions": [r.to_dict() for r in resolutions]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with (out_dir / "review_queue.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["ref_id", "citation", "suggested", "confidence", "reason", "alternatives", "decision"]
        )
        for r in resolutions:
            if r.status != "review":
                continue
            alternatives = " | ".join(c["label"] for c in r.candidates)
            writer.writerow(
                [r.ref_id, r.raw, r.identifier or "", r.confidence, r.rationale, alternatives, ""]
            )

    lines = [
        "# Reference resolution report",
        "",
        f"{facts['references']} references: "
        + ", ".join(f"{n} {s}" for s, n in facts["by_status"].items())
        + f". Automation rate {facts['automation_rate']:.0%}. "
        f"Model cost about ${facts['model']['cost_usd']:.4f} "
        f"({facts['model']['calls']} calls).",
        "",
        "| Ref | Status | Method | Confidence | Resolved to |",
        "|---|---|---|---|---|",
    ]
    for r in resolutions:
        target = f"[{r.identifier}](https://doi.org/{r.identifier})" if r.identifier else ""
        if r.identifier and not r.identifier.startswith("10."):
            target = r.identifier
        lines.append(f"| {r.ref_id} | {r.status} | {r.method} | {r.confidence:.2f} | {target} |")
    lines += ["", "Items marked review are listed in review_queue.csv for a person to confirm."]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return facts
