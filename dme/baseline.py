"""No-model baseline: does any of the top passages cover the scenario's words?

It exists to show what Gemma adds. It is deliberately simple and has one knob, the coverage
threshold, so the benchmark reports a sweep over thresholds instead of a single hand-picked value.
"""
from .retrieve import Retriever, tokens

THRESHOLDS = (0.4, 0.5, 0.6, 0.7, 0.8)


def coverage(retriever, scenario, top_k=3):
    want = set(tokens(scenario["event"] + " " + scenario["required_outcome"]))
    if not want:
        return 0.0
    best = 0.0
    for _, p in retriever.search(scenario["event"] + " " + scenario["required_outcome"], top_k):
        have = set(tokens(p.text + " " + p.heading))
        best = max(best, len(want & have) / len(want))
    return best


def predict(cov, threshold):
    return "Answered" if cov >= threshold else "Not established"
