"""The scan pipeline. Manual runs, scheduled runs and the benchmark all call analyze()."""
import time
from dataclasses import asdict, dataclass

from . import index as ix
from .model import ModelError
from .retrieve import Retriever, tokens
from .validate import (ANSWERED, NOT_ESTABLISHED, UNVERIFIED, SchemaError, dedupe_scenarios,
                       parse_classification, parse_relevance, parse_same, parse_scenarios,
                       parse_situation, verify)

SCENARIO_SYSTEM = """SCENARIO_GENERATION. You are a careful software reviewer.
Read the documentation section and propose failure scenarios: events that could go wrong
for the behavior it describes, where a clear required outcome is needed.
Base scenarios only on operations and behavior described in the text. Do not invent features.
Return ONLY JSON: {"scenarios":[{"event":"...","required_outcome":"..."}]}"""

CLASSIFY_SYSTEM = """EVIDENCE_CLASSIFICATION. Decide whether the PASSAGES establish what must
happen in the SCENARIO. Use exactly one status:
- "Answered": a passage explicitly establishes the required behavior.
- "Partially answered": some behavior is documented but an important condition is unresolved.
- "Contradicted": passages establish incompatible behavior (cite both).
- "Not established": the passages do not establish the required behavior.
Citations must be exact text copied from the passages. Use an empty list for "Not established".
Return ONLY JSON: {"status":"...","citations":[{"file":"...","text":"..."}],
"open_question":"..."}
Write open_question as one concrete question about this scenario, mentioning its event."""

RELEVANCE_SYSTEM = """RELEVANCE_CHECK. You are given a SITUATION, the REQUIRED OUTCOME, and a QUOTE
from the documentation. Does the QUOTE state what happens in this situation, or in an
equivalent one? Different wording is fine: a process that crashes, stops responding or dies
is the same situation as a lease expiring; a device that is no longer signed in is the same
as access being revoked. But the quote must state an OUTCOME (what happens to the work, the
data or the user). A quote that only describes a related mechanism, without saying what
happens in this situation, does not count.
Return ONLY JSON: {"addresses_event": true} or {"addresses_event": false}"""

DESCRIBE_SYSTEM = """DESCRIBE_QUOTE. Read the QUOTE from documentation. In one short sentence, say what
situation the quote is about and what it says happens. Use only what the quote says.
Return ONLY JSON: {"situation": "..."}"""

COMPARE_SYSTEM = """SITUATION_COMPARE. SITUATION_A comes from documentation. SITUATION_B is the scenario
being checked. Are they the same kind of situation, so that what is said about A also tells us
what happens in B? Different wording is fine (a process crashing and a process that stops
responding are the same). A related but different situation is NOT the same (a request returning
an error is not the same as the server losing power).
Return ONLY JSON: {"same_situation": true} or {"same_situation": false}"""


@dataclass
class Stats:
    model_calls: int = 0
    invalid_json: int = 0
    schema_failures: int = 0
    citations_total: int = 0
    citations_valid: int = 0


def _call(model, system, user, stats, parse):
    last = None
    for _ in range(2):  # one retry on malformed output
        stats.model_calls += 1
        try:
            obj = model.generate_json(system, user)
        except ModelError as e:
            stats.invalid_json += 1
            last = e
            continue
        try:
            return parse(obj)
        except SchemaError as e:
            stats.schema_failures += 1
            last = e
    raise last


def _fmt(hits):
    return "\n\n".join(f"[P{i}] {p.file}:{p.start_line}-{p.end_line} ({p.heading})\n{p.text}"
                       for i, (_, p) in enumerate(hits, 1))


def generate_scenarios(model, passages, stats, per_section=3, max_total=12):
    found = []
    for p in passages:
        if len(tokens(p.text)) < 15:
            continue
        user = (f"FILE: {p.file}\nSECTION: {p.heading}\n\n{p.text}\n\n"
                f"Propose up to {per_section} failure scenarios.")
        try:
            items = _call(model, SCENARIO_SYSTEM, user, stats, parse_scenarios)
        except (ModelError, SchemaError):
            continue
        for it in items[:per_section]:
            found.append({**it, "source": f"{p.file}:{p.heading}"})
    return [{"id": f"G{i}", **it} for i, it in enumerate(dedupe_scenarios(found)[:max_total], 1)]


def good_question(q, sc):
    """Reject empty or copied-placeholder questions: it must mention something from the scenario."""
    ref = set(tokens(sc["event"] + " " + sc["required_outcome"]))
    return len(q.strip()) >= 15 and bool(ref & set(tokens(q)))


def _grounded(model, sc, cit, stats, mode):
    """Does this quote establish what happens in the scenario? Two ways to ask a small model."""
    if mode == "describe":  # describe the quote first, without seeing the scenario, then compare
        sit = _call(model, DESCRIBE_SYSTEM, f"QUOTE: {cit['text']}", stats, parse_situation)
        return _call(model, COMPARE_SYSTEM, f"SITUATION_A: {sit}\nSITUATION_B: {sc['event']}",
                     stats, parse_same)
    return _call(model, RELEVANCE_SYSTEM,
                 f"SITUATION: {sc['event']}\nREQUIRED OUTCOME: {sc['required_outcome']}\nQUOTE: {cit['text']}",
                 stats, parse_relevance)


def classify(model, sc, hits, stats, verify_mode="relevance"):
    """Returns (status, citations, open_question, reason)."""
    if not hits:
        return NOT_ESTABLISHED, [], "", "no passage matched"
    user = (f"SCENARIO_ID: {sc['id']}\nEVENT: {sc['event']}\n"
            f"REQUIRED OUTCOME: {sc['required_outcome']}\n\nPASSAGES:\n{_fmt(hits)}")
    try:
        parsed = _call(model, CLASSIFY_SYSTEM, user, stats, parse_classification)
    except (ModelError, SchemaError) as e:
        return UNVERIFIED, [], "", f"model output invalid: {e}"
    res = verify(parsed, [p for _, p in hits])
    if res["status"] != NOT_ESTABLISHED:
        stats.citations_total += res["claimed"]
        stats.citations_valid += res["valid"]
    if res["status"] == ANSWERED and verify_mode != "none":
        try:
            ok = all(_grounded(model, sc, c, stats, verify_mode) for c in res["citations"])
        except (ModelError, SchemaError) as e:
            return UNVERIFIED, res["citations"], parsed["open_question"], f"grounding check invalid: {e}"
        if not ok:
            return (NOT_ESTABLISHED, [], parsed["open_question"],
                    f"cited text does not address the event: {res['citations'][0]['text'][:90]}")
    return res["status"], res["citations"], parsed["open_question"], res["reason"]


def analyze(model, root, synonyms=None, scenarios=None, top_k=3, top_k2=5,
            per_section=3, max_scenarios=12, verify_mode="relevance"):
    t0, stats = time.time(), Stats()
    passages, hashes = ix.build_index(root)
    if not passages:
        raise ValueError(f"no .md or .txt files found under {root}")
    retr = Retriever(passages, synonyms or [])
    mode = "fixed" if scenarios is not None else "generated"
    if scenarios is None:
        scenarios = generate_scenarios(model, passages, stats, per_section, max_scenarios)
    findings = []
    for sc in scenarios:
        query = sc["event"] + " " + sc["required_outcome"]
        status, cits, question, reason = classify(model, sc, retr.search(query, top_k), stats, verify_mode)
        first, used = status, 1
        if status == NOT_ESTABLISHED:  # second pass: synonym expansion, then re-classify
            hits2 = retr.search(query, top_k2, expand=True)
            status, cits, q2, reason = classify(model, sc, hits2, stats, verify_mode)
            question, used = q2 or question, 2
        if not good_question(question, sc):
            question = ""
        findings.append({
            "id": sc["id"], "event": sc["event"], "required_outcome": sc["required_outcome"],
            "source": sc.get("source", ""), "status": status, "first_pass_status": first,
            "pass_used": used, "citations": cits, "reason": reason,
            "open_question": question or f"What must happen when: {sc['event']}?",
        })
    return {"root": str(root), "mode": mode, "verify_mode": verify_mode, "model": model.info(), "files": hashes,
            "findings": findings, "stats": asdict(stats),
            "elapsed_s": round(time.time() - t0, 2)}
