"""Deterministic lexical retrieval with an optional hand-written synonym pass."""
import json
import math
import re
from collections import Counter

STOP = set("""a an and are as at be by for from has have if in is it its of on or that the
this to was were will with when what which who how not no do does can into than then so
but""".split())
TOKEN = re.compile(r"[a-z0-9]+")


def stem(t):
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[: -len(suf)]
    return t


def tokens(text):
    return [stem(t) for t in TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


def load_synonyms(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class Retriever:
    def __init__(self, passages, synonyms=None):
        self.passages = passages
        self.groups = [set(tokens(" ".join(g))) for g in (synonyms or [])]
        self.tf = [Counter(tokens(p.text + " " + p.heading)) for p in passages]
        self.len = [sum(c.values()) for c in self.tf]
        self.df = Counter(t for c in self.tf for t in c)

    def expansion_terms(self, query):
        q = set(tokens(query))
        added = set()
        for g in self.groups:
            if q & g:
                added |= g
        return sorted(added - q)

    def search(self, query, top_k=3, expand=False):
        weights = {t: 1.0 for t in tokens(query)}
        if expand:
            for t in self.expansion_terms(query):
                weights.setdefault(t, 0.5)
        n = len(self.passages)
        scored = []
        for i, p in enumerate(self.passages):
            s = 0.0
            for t, w in weights.items():
                if self.tf[i][t]:
                    idf = math.log((n + 1) / (self.df[t] + 0.5)) + 1
                    s += w * (1 + math.log(self.tf[i][t])) * idf
            if s > 0:
                scored.append((s / math.sqrt(self.len[i] + 1), i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [(round(s, 4), self.passages[i]) for s, i in scored[:top_k]]
