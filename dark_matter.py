#!/usr/bin/env python3
"""Dark Matter Engine: an offline scan for failure scenarios your docs never answered.

  python dark_matter.py scan ./docs
  python dark_matter.py schedule ./docs --at 02:00
  python dark_matter.py bench --runs 3
  python dark_matter.py demo        # everything, one results page
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from dme import guard, index as ix, report
from dme.model import DEFAULT_HOST, ModelError, OllamaModel
from dme.pipeline import analyze
from dme.retrieve import load_synonyms
from dme.validate import NOT_ESTABLISHED, UNVERIFIED

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = os.environ.get("DME_MODEL", "gemma3:4b")  # confirm the tag with `ollama list`
DEFAULT_OUT = "dark_matter_report/latest.html"


def make_model(args):
    if getattr(args, "fake", False):
        from dme.testing import FakeModel
        return FakeModel()
    return OllamaModel(args.model, host=args.host)


def run_scan(root, model, out, force=False, synonyms=None, scenarios=None, verify_mode="relevance"):
    """The one scan path used by `scan`, by the scheduler, and (via analyze) by the benchmark."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cache_path = out.parent / ".dme_cache.json"
    try:
        info, hashes = model.info(), ix.hash_files(root)
        result = None
        if cache_path.exists() and not force:
            cache = json.loads(cache_path.read_text())
            if (cache.get("model") == info and cache.get("hashes") == hashes
                    and cache.get("scenarios") == scenarios
                    and cache.get("verify_mode", "relevance") == verify_mode):
                result = {**cache["result"], "cached": True}
        if result is None:
            result = analyze(model, root, scenarios=scenarios, verify_mode=verify_mode,
                             synonyms=synonyms or load_synonyms(HERE / "data/synonyms.json"))
            cache_path.write_text(json.dumps({"model": info, "hashes": hashes,
                                              "scenarios": scenarios, "verify_mode": verify_mode,
                                              "result": result}))
        out.write_text(report.render(result), encoding="utf-8")
        out.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    except Exception as e:  # never fail silently: the report itself says the run failed
        out.write_text(report.render_failure(e), encoding="utf-8")
        raise


def cmd_scan(a):
    if not a.no_guard:
        guard.install()
    try:
        r = run_scan(a.root, make_model(a), a.out, a.force, verify_mode=getattr(a, "verify_mode", "relevance"))
    except (ModelError, ValueError, OSError) as e:
        print(f"scan failed: {e}", file=sys.stderr)
        return 1
    fs = r["findings"]
    gaps = sum(f["status"] == NOT_ESTABLISHED for f in fs)
    review = sum(f["status"] == UNVERIFIED for f in fs)
    print(f"{len(fs)} scenarios: {gaps} potential gaps, {review} need review. Report: {a.out}")
    return 0


def schedule_command(root, at, out):
    py, script = sys.executable, HERE / "dark_matter.py"
    return f'"{py}" "{script}" scan "{Path(root).resolve()}" --out "{Path(out).resolve()}"'


def windows_schedule_plan(root, at, out):
    """Pure function: the schtasks arguments plus the wrapper script they point at.
    schtasks limits /TR to 261 characters, so /TR points at a short .cmd wrapper that holds the
    full command and appends output to last_run.log next to the report."""
    hh, mm = (int(x) for x in at.split(":"))
    out = Path(out).resolve()
    wrapper, log = out.parent / "run_dark_matter.cmd", out.parent / "last_run.log"
    text = (f'@echo off\r\n"{sys.executable}" "{HERE / "dark_matter.py"}" scan '
            f'"{Path(root).resolve()}" --out "{out}" >> "{log}" 2>&1\r\n')
    args = ["schtasks", "/Create", "/SC", "DAILY", "/TN", "DarkMatterEngine",
            "/TR", f'"{wrapper}"', "/ST", f"{hh:02d}:{mm:02d}", "/F"]
    return args, wrapper, text


POWERSHELL_FIX = ("$t = Get-ScheduledTask -TaskName DarkMatterEngine; "
                  "$t.Settings.DisallowStartIfOnBatteries = $false; "
                  "$t.Settings.StopIfGoingOnBatteries = $false; "
                  "$t.Settings.StartWhenAvailable = $true; "
                  "Set-ScheduledTask -InputObject $t | Out-Null")


def cmd_schedule(a):
    hh, mm = (int(x) for x in a.at.split(":"))
    if os.name == "nt":
        args, wrapper, text = windows_schedule_plan(a.root, a.at, a.out)
        print(f"Wrapper script: {wrapper}\n{text}")
        print("Command: " + subprocess.list2cmdline(args))
        if a.dry_run:
            return 0
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_bytes(text.encode())
        r = subprocess.run(args, capture_output=True, text=True)
        print((r.stdout + r.stderr).strip())
        if r.returncode == 0:
            ps = subprocess.run(["powershell", "-NoProfile", "-Command", POWERSHELL_FIX],
                                capture_output=True, text=True)
            print("Battery settings: " + ("allowed to start on battery, runs after a missed start"
                                          if ps.returncode == 0 else
                                          "NOT changed (" + (ps.stderr or ps.stdout).strip()[:200] + ")"))
            print("Verify:  schtasks /Query /TN DarkMatterEngine /V /FO LIST\n"
                  "Run now: schtasks /Run /TN DarkMatterEngine   (then check last_run.log)")
        return r.returncode
    cmd = schedule_command(a.root, a.at, a.out)
    marker = f"# dark-matter-engine {Path(a.root).resolve()}"
    line = f"{mm} {hh} * * * {cmd} {marker}"
    if a.dry_run:
        print(line)
        return 0
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    keep = [l for l in (cur.stdout.splitlines() if cur.returncode == 0 else []) if marker not in l]
    subprocess.run(["crontab", "-"], input="\n".join(keep + [line]) + "\n", text=True, check=True)
    print(f"Installed daily scan at {a.at}:\n{line}")
    return 0




def cmd_demo(a):
    """One command for judges: A/B scans on the demo specs, benchmark, one results page."""
    from bench.run_bench import run_fixed
    guard.install()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = make_model(a)
    fixed = json.loads((HERE / "bench/fixed_scenarios.json").read_text())
    if a.quick:
        fixed = {"checkout": fixed["checkout"]}
    elif getattr(a, "projects", None):
        fixed = {k: v for k, v in fixed.items() if k in a.projects.split(",")}
    syn = load_synonyms(HERE / "data/synonyms.json")
    try:
        results = {}
        for proj, scenarios in fixed.items():
            for ver in ("v1", "v2"):
                print(f"scanning {proj}/{ver} ...", flush=True)
                results[(proj, ver)] = run_scan(HERE / "corpus" / proj / ver, model,
                                                out / f"{proj}_{ver}" / "latest.html",
                                                synonyms=syn, scenarios=scenarios,
                                                verify_mode=getattr(a, "verify_mode", "relevance"))
        print(f"running benchmark ({a.runs} run(s)) ...", flush=True)
        bench = run_fixed(model, syn, a.runs, projects=list(fixed),
                          verify_mode=getattr(a, "verify_mode", "relevance"))
    except (ModelError, ValueError, OSError) as e:
        print(f"demo failed: {e}\nIs Ollama running with the model pulled ({a.model})?", file=sys.stderr)
        return 1
    (out / "benchmark.json").write_text(json.dumps(bench, indent=2))
    (out / "index.html").write_text(report.render_demo(results, bench, model.info(), a.fake),
                                    encoding="utf-8")
    for proj in fixed:
        for f1, f2 in zip(results[(proj, "v1")]["findings"], results[(proj, "v2")]["findings"]):
            if f1["status"] != f2["status"]:
                print(f"  {proj} {f1['id']}: v1 = {f1['status']}  ->  v2 = {f2['status']}")
    fin, unres = bench["final"], bench["final_unresolved"]
    print(f"unresolved (Not established + Partial): precision {unres['precision']}, recall {unres['recall']}")
    for sp, m in bench["by_split"].items():
        print(f"  [{sp}, n={m['n']}] strict recall {m['strict']['recall']}, FPR {m['strict']['false_positive_rate']}"
              f" | unresolved recall {m['unresolved']['recall']}, FPR {m['unresolved']['false_positive_rate']}")
    print(f"strict gap precision {fin['precision']}, recall {fin['recall']}, "
          f"false-positive rate {fin['false_positive_rate']}, "
          f"JSON validity {bench['json_validity']}, citation validity {bench['citation_validity']}")
    print(f"Open {out / 'index.html'}")
    return 0

def cmd_baseline(a):
    from bench.run_bench import run_baseline
    r = run_baseline()
    print(json.dumps(r, indent=2))
    return 0


def cmd_compare(a):
    """Frozen check (relevance) vs the two-step check (describe), on the same scenarios."""
    from bench.run_bench import run_fixed
    guard.install()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    model = make_model(a)
    syn = load_synonyms(HERE / "data/synonyms.json")
    plan = [("relevance", "heldout2", ["cart", "webhooks", "cache", "export"]),
            ("describe", "heldout2", ["cart", "webhooks", "cache", "export"]),
            ("describe", "dev", ["checkout", "jobs"]),
            ("describe", "heldout", ["auth", "upload", "notifications"])]
    if a.only:
        plan = [p for p in plan if f"{p[0]}:{p[1]}" in a.only.split(",")]
    try:
        for mode, name, projs in plan:
            print(f"[{mode} on {name}] running ...", flush=True)
            r = run_fixed(model, syn, 1, projs, mode)
            (out / f"{mode}_{name}.json").write_text(json.dumps(r, indent=2))
            u, s = r["final_unresolved"], r["final"]
            print(f"  unresolved recall {u['recall']}, false alarms {u['false_positive_rate']}, "
                  f"strict recall {s['recall']}, JSON {r['json_validity']}, {r['runtime_s_per_run']}s")
            for d in r["detail"]:
                flagged = d["status"] in ("Not established", "Partially answered")
                if flagged != (d["expected"] == "Not established"):
                    print(f"    mismatch {d['project']} {d['version']} {d['id']}: "
                          f"expected {d['expected']}, got {d['status']}")
    except (ModelError, OSError) as e:
        print(f"compare failed: {e}", file=sys.stderr)
        return 1
    print(f"Saved in {out}")
    return 0


def cmd_bench(a):
    from bench.run_bench import main
    return main(a)


def build_parser():
    p = argparse.ArgumentParser(prog="dark_matter")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--model", default=DEFAULT_MODEL)
        sp.add_argument("--host", default=DEFAULT_HOST)
        sp.add_argument("--fake", action="store_true", help="stub model, plumbing check only")
        sp.add_argument("--verify-mode", choices=["relevance", "describe", "none"], default="relevance",
                        help="how an Answered claim is double-checked (default: relevance)")

    s = sub.add_parser("scan", help="scan a folder and write the HTML report")
    s.add_argument("root")
    s.add_argument("--out", default=DEFAULT_OUT)
    s.add_argument("--force", action="store_true", help="ignore the unchanged-files cache")
    s.add_argument("--no-guard", action="store_true", help="disable the non-loopback socket guard")
    common(s)
    s.set_defaults(fn=cmd_scan)

    c = sub.add_parser("schedule", help="install a daily overnight scan")
    c.add_argument("root")
    c.add_argument("--at", default="02:00", help="HH:MM, 24-hour")
    c.add_argument("--out", default=DEFAULT_OUT)
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(fn=cmd_schedule)

    d = sub.add_parser("demo", help="run everything: A/B scans, benchmark, one results page")
    d.add_argument("--out-dir", default="demo_output")
    d.add_argument("--runs", type=int, default=1)
    d.add_argument("--projects", help="comma list, e.g. auth,upload,notifications")
    d.add_argument("--quick", action="store_true", help="checkout pair only (shorter run)")
    common(d)
    d.set_defaults(fn=cmd_demo)

    k = sub.add_parser("compare", help="frozen relevance check vs two-step describe check")
    k.add_argument("--out-dir", default="compare_output")
    k.add_argument("--only", help="e.g. relevance:heldout2,describe:dev")
    k.add_argument("--model", default=DEFAULT_MODEL)
    k.add_argument("--host", default=DEFAULT_HOST)
    k.add_argument("--fake", action="store_true")
    k.set_defaults(fn=cmd_compare)

    n = sub.add_parser("baseline", help="no-model baseline over the same scenarios")
    n.set_defaults(fn=cmd_baseline)

    b = sub.add_parser("bench", help="run the benchmark on corpus/")
    b.add_argument("--runs", type=int, default=3)
    b.add_argument("--projects", help="comma list, e.g. cart,webhooks,cache,export")
    b.add_argument("--mode", choices=["fixed", "generated", "both"], default="fixed")
    common(b)
    b.set_defaults(fn=cmd_bench)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    sys.exit(args.fn(args))
