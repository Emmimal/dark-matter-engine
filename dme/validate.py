"""Deterministic checks. Nothing here depends on the model's own confidence."""
import re
from .retrieve import tokens

ANSWERED = "Answered"
PARTIAL = "Partially answered"
CONTRADICTED = "Contradicted"
NOT_ESTABLISHED = "Not established"
UNVERIFIED = "Unverified (needs review)"
MODEL_STATUSES = {ANSWERED, PARTIAL, CONTRADICTED, NOT_ESTABLISHED}
MIN_CITATION_CHARS = 12


class SchemaError(ValueError):
    pass


def parse_scenarios(obj):
    items = obj.get("scenarios") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise SchemaError("missing 'scenarios' list")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise SchemaError("scenario is not an object")
        ev, oc = it.get("event"), it.get("required_outcome")
        if not (isinstance(ev, str) and ev.strip() and isinstance(oc, str) and oc.strip()):
            raise SchemaError("scenario needs non-empty event and required_outcome")
        out.append({"event": ev.strip(), "required_outcome": oc.strip()})
    return out


def parse_relevance(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("addresses_event"), bool):
        raise SchemaError("expected {'addresses_event': true|false}")
    return obj["addresses_event"]


def parse_situation(obj):
    s = obj.get("situation") if isinstance(obj, dict) else None
    if not (isinstance(s, str) and s.strip()):
        raise SchemaError("expected {'situation': '...'}")
    return s.strip()


def parse_same(obj):
    if not isinstance(obj, dict) or not isinstance(obj.get("same_situation"), bool):
        raise SchemaError("expected {'same_situation': true|false}")
    return obj["same_situation"]


def parse_classification(obj):
    if not isinstance(obj, dict):
        raise SchemaError("not an object")
    status = obj.get("status")
    if status not in MODEL_STATUSES:
        raise SchemaError(f"invalid status: {status!r}")
    cits = obj.get("citations", [])
    if not isinstance(cits, list) or not all(
        isinstance(c, dict) and isinstance(c.get("text"), str) for c in cits
    ):
        raise SchemaError("citations must be a list of {file,text}")
    q = obj.get("open_question", "")
    return {"status": status, "citations": cits, "open_question": q if isinstance(q, str) else ""}


def locate_citation(text, passages):
    """Find the cited text inside the retrieved passages (whitespace/case tolerant)."""
    words = text.split()
    if len(" ".join(words)) < MIN_CITATION_CHARS:
        return None
    rx = re.compile(r"\s+".join(map(re.escape, words)), re.I)
    for p in passages:
        m = rx.search(p.text)
        if m:
            s = p.start_line + p.text.count("\n", 0, m.start())
            e = p.start_line + p.text.count("\n", 0, m.end())
            return {"file": p.file, "line_start": s, "line_end": e, "text": m.group(0)}
    return None


def verify(parsed, passages):
    """Return dict(status, citations, reason, claimed, valid)."""
    status = parsed["status"]
    if status == NOT_ESTABLISHED:
        return {"status": status, "citations": [], "reason": "", "claimed": 0, "valid": 0}
    claimed = parsed["citations"]
    located = [loc for loc in (locate_citation(c["text"], passages) for c in claimed) if loc]
    res = {"claimed": len(claimed), "valid": len(located)}
    if not claimed or len(located) < len(claimed):
        return {**res, "status": UNVERIFIED, "citations": located,
                "reason": "citation not found in retrieved passages"}
    if status == CONTRADICTED and len({(l["file"], l["line_start"]) for l in located}) < 2:
        return {**res, "status": UNVERIFIED, "citations": located,
                "reason": "contradiction needs two distinct cited passages"}
    return {**res, "status": status, "citations": located, "reason": ""}


def dedupe_scenarios(items, threshold=0.7):
    kept, sigs = [], []
    for it in items:
        sig = set(tokens(it["event"] + " " + it["required_outcome"]))
        if any(sig and o and len(sig & o) / len(sig | o) >= threshold for o in sigs):
            continue
        kept.append(it)
        sigs.append(sig)
    return kept
