"""Command line: `refresolver run | cite | eval | serve`. Logs go to stderr."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from pathlib import Path

from .config import Settings


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    changes = {}
    if getattr(args, "cache_dir", None):
        changes["cache_dir"] = Path(args.cache_dir)
    if getattr(args, "offline", False):
        changes["offline"] = True
    return dataclasses.replace(settings, **changes)


def _resolver(args, settings):
    from .factory import build_resolver

    use_llm = False if getattr(args, "no_llm", False) else None
    return build_resolver(settings, use_llm=use_llm, use_agent=not getattr(args, "no_agent", False))


def _run(args) -> int:
    from .report import write_outputs

    settings = _settings(args)
    resolver = _resolver(args, settings)
    text = Path(args.file).read_text(encoding="utf-8")
    refs = resolver.references_from_text(text)
    if not refs:
        print("No references found.", file=sys.stderr)
        return 2
    print(f"Resolving {len(refs)} references...", file=sys.stderr)
    resolutions = resolver.resolve_all(refs)
    facts = write_outputs(resolutions, resolver.meter, Path(args.out))
    print(json.dumps(facts, indent=2))
    print(f"Wrote {args.out}/report.md, resolutions.json and review_queue.csv", file=sys.stderr)
    return 0


def _cite(args) -> int:
    settings = _settings(args)
    resolver = _resolver(args, settings)
    resolution = resolver.resolve(resolver.parse([args.citation])[0])
    print(json.dumps(resolution.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _eval(args) -> int:
    from .evaluation import evaluate, load_gold

    settings = _settings(args)
    resolver = _resolver(args, settings)
    gold = load_gold(Path(args.gold))
    result, resolutions = evaluate(resolver, gold)
    lines = [
        f"# Evaluation: {Path(args.gold).name}",
        "",
        f"Model: {settings.model if resolver.llm else 'none (deterministic only)'}; "
        f"agent: {'on' if resolver.llm and resolver.use_agent else 'off'}.",
        "",
        result.table(),
        "",
        "## Calibration",
        "",
        f"Thresholds in this run: auto-link at score >= {settings.auto_accept} with a lead of "
        f">= {settings.min_margin}; model-assisted link at confidence >= {settings.llm_accept} "
        f"and score >= {settings.review_floor}.",
        "",
        result.calibration_table(),
        "",
        "## Errors",
        "",
    ] + [f"- {json.dumps(e)}" for e in result.errors]
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "eval.md").write_text(report, encoding="utf-8")
        (out / "eval_resolutions.json").write_text(
            json.dumps([r.to_dict() for r in resolutions], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    ok = result.passed(args.min_precision)
    print("PASS" if ok else f"FAIL (need precision >= {args.min_precision} and no false links)")
    return 0 if ok else 1


def _calibrate(args) -> int:
    """Calibration tables from a saved run (eval_resolutions.json, or resolutions.json from a
    run over a document whose answers a person has since confirmed in a gold file)."""
    from .evaluation import load_gold, score_resolutions
    from .models import Resolution

    gold = load_gold(Path(args.gold))
    data = json.loads(Path(args.resolutions).read_text(encoding="utf-8"))
    resolutions = [Resolution(**r) for r in data]
    if len(resolutions) != len(gold):
        print(f"{len(resolutions)} resolutions for {len(gold)} gold items", file=sys.stderr)
        return 2
    print(score_resolutions(gold, resolutions).calibration_table())
    return 0


def _serve(args) -> int:
    from .mcp_server import create_server

    server = create_server(_settings(args))
    if args.transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host="127.0.0.1", port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="refresolver", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--no-llm", action="store_true", help="deterministic steps only")
        p.add_argument("--no-agent", action="store_true", help="no search agent")
        p.add_argument("--cache-dir", help="where HTTP and model responses are recorded")
        p.add_argument("--offline", action="store_true", help="replay recorded responses only")

    p = sub.add_parser("run", help="resolve the bibliography of a document")
    p.add_argument("file")
    p.add_argument("--out", default="out")
    common(p)

    p = sub.add_parser("cite", help="resolve one citation")
    p.add_argument("citation")
    common(p)

    p = sub.add_parser("eval", help="measure quality on a gold set")
    p.add_argument("gold")
    p.add_argument("--out")
    p.add_argument("--min-precision", type=float, default=0.95)
    common(p)

    p = sub.add_parser("calibrate", help="calibration tables from a saved evaluation run")
    p.add_argument("gold")
    p.add_argument("resolutions", help="eval_resolutions.json from `refresolver eval --out`")

    p = sub.add_parser("serve", help="run as an MCP server")
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    p.add_argument("--port", type=int, default=8001)
    common(p)

    args = parser.parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    handlers = {
        "run": _run,
        "cite": _cite,
        "eval": _eval,
        "calibrate": _calibrate,
        "serve": _serve,
    }
    from .fetch import CacheMiss
    from .llm import ReplayMiss

    try:
        return handlers[args.command](args)
    except (CacheMiss, ReplayMiss) as exc:
        reason = str(exc).rstrip(".")
        print(f"Replay incomplete: {reason}. Record again without --offline.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
