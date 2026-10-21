"""Standalone HTML report: summary first, potential gaps next, everything else after."""
import datetime
import html

from .validate import ANSWERED, NOT_ESTABLISHED, UNVERIFIED

CSS = """:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--card:#f6f6f4;--bd:#ddd;--gap:#b3261e;--rev:#8a5a00}
@media(prefers-color-scheme:dark){:root{--bg:#161616;--fg:#eee;--mut:#aaa;--card:#202020;--bd:#383838;--gap:#ff8a80;--rev:#ffcc80}}
body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem}
h1{font-size:1.5rem}.mut{color:var(--mut);font-size:.9rem}.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:1rem;margin:.8rem 0}
.gap{color:var(--gap);font-weight:600}.rev{color:var(--rev);font-weight:600}blockquote{margin:.4rem 0;padding-left:.8rem;border-left:3px solid var(--bd)}
code{font-size:.85rem}details summary{cursor:pointer}"""


def _page(title, body):
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>")


def _evidence(f):
    if not f["citations"]:
        return "<p class='mut'>No supporting passage cited.</p>"
    return "".join(f"<blockquote>{html.escape(c['text'])}<br><code>{html.escape(c['file'])}:"
                   f"{c['line_start']}-{c['line_end']}</code></blockquote>" for c in f["citations"])


def _card(f):
    if f["status"] == NOT_ESTABLISHED:
        tag = "<span class='gap'>Potential gap: not established in the inspected documentation</span>"
    elif f["status"] == UNVERIFIED:
        tag = f"<span class='rev'>Needs review</span> <span class='mut'>({html.escape(f['reason'])})</span>"
    else:
        tag = f"<strong>{html.escape(f['status'])}</strong>"
    return (f"<div class='card'>{tag}<p><strong>{html.escape(f['event'])}</strong><br>"
            f"<span class='mut'>Required: {html.escape(f['required_outcome'])}</span></p>"
            f"<p>Question to resolve: {html.escape(f['open_question'])}</p>{_evidence(f)}"
            f"<p class='mut'>Found in pass {f['pass_used']} &middot; {html.escape(f['source'])}</p></div>")


def render(result):
    fs = result["findings"]
    gaps = [f for f in fs if f["status"] == NOT_ESTABLISHED]
    review = [f for f in fs if f["status"] == UNVERIFIED]
    partial = [f for f in fs if f['status'] not in (ANSWERED, NOT_ESTABLISHED, UNVERIFIED)]
    rest = [f for f in fs if f['status'] == ANSWERED]
    m = result["model"]
    top = "".join(f"<li>{html.escape(f['open_question'])}</li>" for f in (gaps + partial)[:3]) or "<li>No potential gaps found.</li>"
    note = " (no changes since last run; cached)" if result.get("cached") else ""
    body = (f"<h1>Dark Matter Engine report</h1>"
            f"<p><strong>{len(gaps)}</strong> potential gaps &middot; {len(partial)} partial or contradicted &middot; "
            f"{len(review)} need review &middot; {len(rest)} answered, of {len(fs)} scenarios{note}.</p>"
            f"<p><strong>Top questions to resolve:</strong></p><ol>{top}</ol>"
            f"<p class='mut'>Model {html.escape(str(m.get('tag')))} (digest {html.escape(str(m.get('digest')))}) "
            f"&middot; {len(result['files'])} files &middot; {result['elapsed_s']}s &middot; mode {result['mode']} "
            f"&middot; generated {datetime.datetime.now().isoformat(timespec='seconds')}</p>"
            f"<h2>Potential gaps</h2>{''.join(map(_card, gaps)) or '<p class=mut>None.</p>'}"
            f"<h2>Partially answered or contradicted</h2>{''.join(map(_card, partial)) or '<p class=mut>None.</p>'}"
            f"<h2>Needs review</h2>{''.join(map(_card, review)) or '<p class=mut>None.</p>'}"
            f"<details><summary>Answered ({len(rest)})</summary>"
            f"{''.join(map(_card, rest))}</details>"
            f"<p class='mut'>A potential gap means the inspected files did not establish the behavior. "
            f"It is a question to check, not proof the behavior is undefined.</p>")
    return _page("Dark Matter Engine report", body)


def render_failure(error):
    body = (f"<h1>Dark Matter Engine: scan FAILED</h1><p class='gap'>{html.escape(str(error))}</p>"
            f"<p class='mut'>{datetime.datetime.now().isoformat(timespec='seconds')} &middot; "
            f"This is not a clean result. Previous results were not reused.</p>")
    return _page("Dark Matter Engine: scan failed", body)


def render_demo(results, bench, model, fake=False):
    """Single results page: v1 vs v2 per scenario, links to full reports, benchmark metrics."""
    rows = ""
    for proj in sorted({k[0] for k in results}):
        v1, v2 = results[(proj, "v1")]["findings"], results[(proj, "v2")]["findings"]
        for a, b in zip(v1, v2):
            changed = " class='gap'" if a["status"] != b["status"] else ""
            rows += (f"<tr><td>{html.escape(proj)}</td><td>{html.escape(a['id'])}</td>"
                     f"<td>{html.escape(a['event'])}</td><td{changed}>{html.escape(a['status'])}</td>"
                     f"<td>{html.escape(b['status'])}</td></tr>")
    links = "".join(f"<li><a href='{p}_{v}/latest.html'>{p} {v}</a></li>"
                    for p in sorted({k[0] for k in results}) for v in ("v1", "v2"))
    fin, first = bench["final"], bench["first_pass_only"]
    metric = lambda n, v: f"<tr><td>{n}</td><td>{html.escape(str(v))}</td></tr>"
    mt = "".join([
        metric("Gap precision", fin["precision"]), metric("Gap recall", fin["recall"]),
        metric("False-positive rate", fin["false_positive_rate"]),
        metric("Unresolved precision (Not established + Partial)", bench["final_unresolved"]["precision"]),
        metric("Unresolved recall (added after the first run)", bench["final_unresolved"]["recall"]),
        metric("Unresolved false-positive rate", bench["final_unresolved"]["false_positive_rate"]),
        "".join(metric(f"[{sp}, n={m['n']}] strict recall / FPR", f"{m['strict']['recall']}  /  {m['strict']['false_positive_rate']}")
                + metric(f"[{sp}, n={m['n']}] unresolved recall / FPR", f"{m['unresolved']['recall']}  /  {m['unresolved']['false_positive_rate']}")
                for sp, m in bench["by_split"].items()),
        metric("Unverified findings", fin["unverified"]),
        metric("Precision, first pass only", first["precision"]),
        metric("Valid answers rescued by second pass", bench["second_pass_rescued_valid_answers"]),
        metric("Real gaps the second pass turned into Answered", bench["second_pass_hid_real_gaps"]),
        metric("Citation validity", bench["citation_validity"]),
        metric("JSON validity", bench["json_validity"]),
        metric(f"Repeat consistency ({bench['runs']} run(s))", bench["repeat_consistency"]),
        metric("Runtime per run (s)", bench["runtime_s_per_run"])])
    warn = ("<p class='gap'>Stub model: this checks the harness only. These are NOT model results.</p>"
            if fake else "")
    body = (f"<h1>Dark Matter Engine: demo results</h1>{warn}"
            f"<p class='mut'>Model {html.escape(str(model.get('tag')))} (digest "
            f"{html.escape(str(model.get('digest')))}). Fixed scenarios on small planted specs; "
            f"v1 omits a behavior, v2 documents it.</p>"
            f"<h2>v1 (omission) vs v2 (documented)</h2><table border='0' cellpadding='6'>"
            f"<tr><th>Project</th><th>ID</th><th>Scenario</th><th>v1</th><th>v2</th></tr>{rows}</table>"
            f"<h2>Benchmark ({bench['n_scenarios']} scenarios; first three rows are the strict metric)</h2><table cellpadding='6'>{mt}</table>"
            f"<p class='mut'>Small sample: one miss moves a percentage a lot. Not compared to closed models.</p>"
            f"<h2>Full reports</h2><ul>{links}</ul>")
    return _page("Dark Matter Engine: demo results", body)
