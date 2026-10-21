# Dark Matter Engine

An offline scan that finds the failure questions your documentation never answered.
Point it at a folder of Markdown/text docs. Overnight, a local Gemma model proposes failure
scenarios from the behavior your docs describe, local search looks for evidence that each one
is handled, and you get one HTML report in the morning.

A "potential gap" means the inspected files did not establish the behavior. It is a question
to check, not proof that the behavior is undefined.

## Run it (judges: this is the only command you need)

```bash
ollama pull gemma3:4b                    # confirm the tag you use with `ollama list`
python dark_matter.py demo                 # everything: A/B scans, benchmark, one results page
# slow machine? add --quick (checkout pair only)
python dark_matter.py scan ./docs        # scan your own docs (no pip install needed)
open demo_output/index.html
```

`demo` uses the bundled spec pairs with fixed scenarios, so the v1-vs-v2 result does not depend on
which scenarios the model happens to propose. `scan` lets the model generate them.

Overnight: `python dark_matter.py schedule ./docs --at 02:00` installs a daily cron entry
(Task Scheduler on Windows). It calls the same `scan` command, so scheduled and manual runs
share one code path. Unchanged files reuse the cached result. A failed run writes a report
that says it failed.

Set another model with `--model` or `DME_MODEL`. Ollama is the one external runtime.

## How it avoids made-up gaps

1. Scenarios come from sections the docs actually contain, not from "what is missing".
2. Lexical retrieval fetches evidence before the model classifies anything.
3. Statuses: Answered, Partially answered, Contradicted, Not established, and
   **Unverified (needs review)**.
4. Every citation is checked against the retrieved text. A citation that is not found makes
   the finding Unverified, never a gap. Contradicted needs two distinct cited passages.
5. A Not established result triggers a second pass: hand-written synonym expansion
   (`data/synonyms.json`), then re-classification.

## Benchmark

`corpus/` holds with/without spec pairs. `bench/ground_truth.json` holds the expected
outcomes and is never read by the scanner.

```bash
python dark_matter.py bench --runs 3 --mode both --model gemma3:4b
```

It reports gap precision, gap recall, false-positive rate (each with its sample size),
first-pass vs final results, how many valid answers the second pass rescued and how many real
gaps it hid, citation validity, JSON validity, repeat consistency, and runtime.
`--fake` runs a stub model to check the harness only; those numbers say nothing about Gemma.

## Offline claims, and their limits

- The engine installs a guard that blocks non-loopback connections and DNS lookups in its own
  process (see `tests/test_core.py`, class `Offline`).
- That does not prove what the Ollama installation does. Show the Wi-Fi-off run as the
  separate check.

## Known limits

Markdown and text only. The corpus is small (2 pairs); add more before quoting percentages.
No contradiction case is in the corpus yet. Not compared against closed models.

Tests: `python -m unittest discover -s tests`
