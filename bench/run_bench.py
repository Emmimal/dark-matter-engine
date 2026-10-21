"""Benchmark: expected outcomes live in bench/ground_truth.json; the scanner never sees them."""
import json
import math
import time
from pathlib import Path

from dme import guard
from dme.pipeline import analyze
from dme.retrieve import load_synonyms, tokens
from dme.validate import NOT_ESTABLISHED, PARTIAL, UNVERIFIED

ROOT = Path(__file__).resolve().parent.parent
GT = json.loads((ROOT / "bench/ground_truth.json").read_text())["items"]
FIXED = json.loads((ROOT / "bench/fixed_scenarios.json").read_text())


def frac(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a (0 items)"


def score(items, key, unresolved=False):
    """Gap precision/recall/FPR from findings; key picks 'status' (final) or 'first_pass_status'."""
    tp = fp = fn = pos = neg = unv = 0
    for it, f in items:
        pred = f[key] in ((NOT_ESTABLISHED, PARTIAL) if unresolved else (NOT_ESTABLISHED,))
        unv += f[key] == UNVERIFIED
        if it["expected"] == NOT_ESTABLISHED:
            pos += 1
            tp += pred
            fn += not pred
        else:
            neg += 1
            fp += pred
    return {"precision": frac(tp, tp + fp), "recall": frac(tp, pos),
            "false_positive_rate": frac(fp, neg), "unverified": f"{unv}/{len(items)}",
            "tp": tp, "fp": fp, "fn": fn}


def run_fixed(model, syn, runs, projects=None):
    gt = [it for it in GT if not projects or it["project"] in projects]
    all_runs, t0 = [], time.time()
    for r in range(runs):
        by_key, stats = {}, {"model_calls": 0, "invalid_json": 0, "schema_failures": 0,
                             "citations_total": 0, "citations_valid": 0}
        for proj, scenarios in FIXED.items():
            if projects and proj not in projects:
                continue
            for ver in ("v1", "v2"):
                res = analyze(model, ROOT / "corpus" / proj / ver, synonyms=syn, scenarios=scenarios)
                for f in res["findings"]:
                    by_key[(proj, ver, f["id"])] = f
                for k in stats:
                    stats[k] += res["stats"][k]
        all_runs.append((by_key, stats))
    elapsed = time.time() - t0
    by_key, stats = all_runs[0]
    items = [(it, by_key[(it["project"], it["version"], it["scenario_id"])]) for it in gt]
    stable = sum(len({r[0][(it["project"], it["version"], it["scenario_id"])]["status"]
                      for r in all_runs}) == 1 for it in gt)
    rescued = sum(f["first_pass_status"] == NOT_ESTABLISHED and f["status"] == "Answered"
                  and it["expected"] == "Answered" for it, f in items)
    harmed = sum(f["first_pass_status"] == NOT_ESTABLISHED and f["status"] not in (NOT_ESTABLISHED, PARTIAL)
                 and it["expected"] == NOT_ESTABLISHED for it, f in items)
    by_split = {}
    for sp in sorted({it.get("split", "dev") for it, _ in items}):
        sub = [(it, f) for it, f in items if it.get("split", "dev") == sp]
        by_split[sp] = {"n": len(sub), "strict": score(sub, "status"),
                        "unresolved": score(sub, "status", True)}
    calls = stats["model_calls"]
    return {
        "mode": "fixed", "n_scenarios": len(items), "runs": runs,
        "final": score(items, "status"), "final_unresolved": score(items, "status", True), "by_split": by_split, "first_pass_only": score(items, "first_pass_status"),
        "second_pass_rescued_valid_answers": rescued, "second_pass_hid_real_gaps": harmed,
        "citation_validity": frac(stats["citations_valid"], stats["citations_total"]),
        "json_validity": frac(calls - stats["invalid_json"] - stats["schema_failures"], calls),
        "repeat_consistency": frac(stable, len(gt)),
        "runtime_s_per_run": round(elapsed / runs, 2),
    }


def run_generated(model, syn):
    """Scenario recall: did generation produce a scenario matching each planted omission?"""
    found = total = 0
    detail = []
    for it in (i for i in GT if i["class"] == "planted"):
        res = analyze(model, ROOT / "corpus" / it["project"] / it["version"], synonyms=syn)
        need = math.ceil(len(it["match_terms"]) / 2) + 1 if len(it["match_terms"]) > 2 else 2
        want = set(tokens(" ".join(it["match_terms"])))
        hit = [f for f in res["findings"]
               if len(want & set(tokens(f["event"] + " " + f["required_outcome"]))) >= min(need, len(want))]
        total += 1
        found += bool(hit)
        detail.append({"project": it["project"], "version": it["version"], "generated": len(res["findings"]),
                       "matched": bool(hit), "status": hit[0]["status"] if hit else None})
    return {"mode": "generated", "scenario_recall": frac(found, total), "detail": detail}


def main(a):
    from dark_matter import make_model
    guard.install()
    model, syn = make_model(a), load_synonyms(ROOT / "data/synonyms.json")
    out = {"model": model.info(), "plumbing_check_only": bool(a.fake)}
    if a.mode in ("fixed", "both"):
        out["fixed"] = run_fixed(model, syn, a.runs)
    if a.mode in ("generated", "both"):
        out["generated"] = run_generated(model, syn)
    (ROOT / "bench/results.json").write_text(json.dumps(out, indent=2))
    if a.fake:
        print("NOTE: stub model. This checks the harness only. These are NOT model results.\n")
    print(json.dumps(out, indent=2))
    return 0
