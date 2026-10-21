# Dark Matter Engine

An offline scan that finds the failure questions your documentation never answered.

Point it at a folder of Markdown or text docs. A local Gemma model (through Ollama) proposes failure
scenarios from the behavior the docs describe, local search looks for evidence that each one is handled,
and you get one HTML report. Run it on a schedule and the report is waiting in the morning.

A **potential gap** means the inspected files did not establish the behavior. It is a question for an
engineer to check, not proof that the behavior is undefined.

Built for the Hacktoberfest Open-Source AI Challenge, Week 3 (Slow and Steady). Python standard library
only, no pip install. Ollama is the one external runtime.

## Run it

```bash
ollama pull gemma3:4b          # check the exact tag with `ollama list`
python dark_matter.py demo --quick
```

`demo --quick` scans the checkout spec pair and runs the benchmark on it. It took about 5 minutes on the
author's laptop. Then open `demo_output/index.html` (Windows: `start demo_output\index.html`).

- `python dark_matter.py demo` runs all five spec pairs (30 scenarios). About 26 minutes per run.
- `python dark_matter.py scan ./docs` scans your own folder. Here the model writes its own scenarios.
- `python dark_matter.py schedule ./docs --at 02:00` installs a daily overnight scan (cron, or Task
  Scheduler on Windows). It runs the same `scan` command. Unchanged files reuse the saved result.
- Tests: `python -m unittest discover -s tests`

Model: `gemma3:4b`, digest `68ceab7e468a` (full digest is on the results page). Temperature 0, fixed seed.

## How it avoids made-up gaps

1. Scenarios come from sections the docs actually contain.
2. Lexical retrieval fetches the evidence before the model classifies anything.
3. Statuses: Answered, Partially answered, Contradicted, Not established, and Unverified (needs review).
4. Every citation is checked against the retrieved text. A citation that is not found makes the finding
   Unverified, never a gap. Contradicted needs two distinct cited passages.
5. An Answered claim gets a second, narrow yes/no check: does the quote say what happens in this situation?
6. Not established triggers a second pass: hand-written synonym expansion (`data/synonyms.json`), then
   re-classification.

## Benchmark

`corpus/` holds five with/without spec pairs: v1 omits one behavior, v2 documents it. Expected outcomes are in
`bench/ground_truth.json`, which the scanner never reads. The benchmark uses fixed scenarios, so it tests
evidence classification separately from whether the model can invent good scenarios.

**Dev pairs** (checkout, jobs; used to tune prompts) and **held-out pairs** (auth, upload, notifications;
written after the prompts were tuned, run once, no changes since). Final run: 30 scenarios, two runs, same
machine.

| Result | Count |
|---|---|
| Held-out: planted gaps flagged as unresolved (Not established or Partially answered) | 3 of 3 |
| Held-out: documented scenarios wrongly flagged | 0 of 15 |
| Dev: planted gaps flagged as unresolved | 1 of 2 |
| Dev: documented scenarios wrongly flagged | 0 of 10 |
| Strict metric (Not established only): gaps found | 1 of 5 |
| Fix recognized (v2 flips to Answered) | 4 of 4 flagged gaps |
| Valid JSON from the model | 64 of 64 calls |
| Citations found in the cited text | 34 of 34 |
| Second pass rescued a documented scenario | 1 |
| Second pass turned a real gap into Answered | 0 |
| Repeat consistency across 2 runs | 30 of 30 |

The counts are small. One miss moves a percentage a lot, so read the counts, not percentages.

### Things to know before trusting the numbers

- **Strict recall is low (1 of 5).** Gemma usually labels an omission "Partially answered", because the docs do
  cover the topic and only miss the specific case. I report both metrics. The "unresolved" metric was
  defined after the first run.
- **Known failure (jobs J1).** For "a worker process crashes while running a job", Gemma cited the sentence
  about retrying a job after it raises an error and called the scenario Answered. The citation is real, but
  the inference is not supported: retrying after an error does not establish recovery after a crash. The
  citation check cannot catch this, and a relevance check added to catch it did not. This is a limitation of
  the current classifier on the 4B model, left unfixed.
- **Tuning history.** The first full run on the dev pairs found 0 of 2 planted gaps. I then added the
  relevance check, the partial-answer reporting and the unresolved metric, using only the dev pairs. The
  held-out pairs were run once with the final prompts. Earlier results are kept in `evidence/first_run_demo_output`
  (its page uses an older definition of one metric, "gaps hidden by second pass").
- **Same machine, fixed seed.** Identical results across two runs show determinism on one machine, not
  robustness across machines or models.
- **Scenario generation is weaker than classification.** On a plain `scan`, the model invents some
  requirements the spec never states. In the scheduled run on checkout/v1, one flagged "gap" was a false alarm
  (the spec does define behavior on a gateway 500). It also did not produce the lost-response retry scenario.
  Treat generated scenarios as prompts for review, not as findings.
- Not compared against closed models. Markdown and text only. No contradiction case in the corpus yet.

## Offline and scheduled use

- The engine blocks non-loopback network connections and DNS lookups inside its own process, and refuses
  any model host that is not localhost (see `tests/test_core.py`, class `Offline`). That covers the Python
  process only, not the Ollama installation.
- Offline run: Wi-Fi off, `ping google.com` failing, then `demo --quick` completed with the same result. See
  `evidence/dark-matter-engine.mp4` and `evidence/offline_results.png`.
- Scheduled run: a Windows Task Scheduler task ran by itself (last result 0), wrote the report and a log,
  and a second run on unchanged files reused the saved result. See `evidence/`. The overnight run needs the
  laptop awake and Ollama running. Task Scheduler blocks starting on battery by default; I changed that setting by hand for this test.

## Layout

```
dark_matter.py   CLI: scan, schedule, demo, bench
dme/             index, retrieve, model (Ollama), validate, pipeline, report, guard
data/            synonym groups (hand-written)
corpus/          five with/without spec pairs
bench/           scenarios, ground truth (never read by the scanner), benchmark runner
evidence/        recordings, logs and result pages from the runs above
tests/           unit tests (use a stub model; they check plumbing, not Gemma)
```

`--fake` runs a stub model. Those numbers check the harness only and say nothing about Gemma.

MIT licensed.
