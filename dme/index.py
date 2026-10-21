"""Local indexing: split .md/.txt files into passages that keep line numbers."""
import hashlib
import os
import re
from dataclasses import dataclass

EXTS = {".md", ".txt"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "dist", "build"}
HEADING = re.compile(r"^#{1,6}\s+(.*\S)")


@dataclass(frozen=True)
class Passage:
    file: str
    heading: str
    start_line: int  # 1-based, inclusive
    end_line: int
    text: str


def list_files(root):
    root_real = os.path.realpath(root)
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x not in SKIP_DIRS)
        for f in sorted(files):
            p = os.path.join(d, f)
            if f.startswith(".") or os.path.splitext(f)[1].lower() not in EXTS:
                continue
            if not os.path.realpath(p).startswith(root_real + os.sep):
                continue  # symlink escaping the selected root
            out.append(p)
    return out


def hash_files(root):
    hashes = {}
    for p in list_files(root):
        with open(p, "rb") as fh:
            hashes[os.path.relpath(p, root)] = hashlib.sha256(fh.read()).hexdigest()
    return hashes


def _split_markdown(lines):
    sections, start, heading = [], 1, "(intro)"
    for i, line in enumerate(lines, 1):
        m = HEADING.match(line)
        if m:
            if i > start:
                sections.append((heading, start, i - 1))
            heading, start = m.group(1), i
    sections.append((heading, start, len(lines)))
    return sections


def _split_paragraphs(lines):
    sections, start = [], None
    for i, line in enumerate(lines + [""], 1):
        if line.strip() and start is None:
            start = i
        elif not line.strip() and start is not None:
            head = " ".join(lines[start - 1].split()[:6])
            sections.append((head, start, i - 1))
            start = None
    return sections


def build_index(root):
    passages = []
    for p in list_files(root):
        with open(p, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        rel = os.path.relpath(p, root)
        split = _split_markdown if p.lower().endswith(".md") else _split_paragraphs
        for heading, s, e in split(lines):
            text = "\n".join(lines[s - 1:e])
            if text.strip():
                passages.append(Passage(rel, heading, s, e, text))
    return passages, hash_files(root)
