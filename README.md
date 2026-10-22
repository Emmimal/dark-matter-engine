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

- `python dark_matter.py demo` runs every spec pair (54 scenarios). It takes roughly an hour or more on the
  author's laptop (not re-timed since the corpus grew).
- `python dark_matter.py scan ./docs` scans your own folder. Here the model writes its own scenarios.
- `python dark_matter.py schedule ./docs --at 02:00` installs a daily overnight scan (cron, or Task
  Scheduler on Windows). It runs the same `scan` command. Unchanged files reuse the saved result.
- `python dark_matter.py baseline` runs a no-model baseline over the same scenarios (seconds).
- `python dark_matter.py compare` runs the two verification modes side by side (about 80 minutes).
- `--verify-mode relevance|describe|none` chooses how an Answered claim is double-checked.
- Tests: `python -m unittest discover -s tests` (stub model; they check plumbing, not Gemma).

Model: `gemma3:4b`, digest `68ceab7e468a` (full digest is in the result files). Temperature 0, fixed seed.

## How it avoids made-up gaps

1. Scenarios come from sections the docs actually contain.
2. Lexical retrieval fetches the evidence before the model classifies anything.
3. Statuses: Answered, Partially answered, Contradicted, Not established, and Unverified (needs review).
4. Every citation is checked against the retrieved text. A citation that is not found makes the finding
   Unverified, never a gap. Contradicted needs two distinct cited passages.
5. An Answered claim gets a second check, in one of two modes:
   - `relevance` (default): one yes/no call. Does the quote say what happens in this situation?
   - `describe`: Gemma first describes what the quote is about without seeing the scenario, then a
     separate call compares that description with the scenario.
6. Not established triggers a second pass: hand-written synonym expansion (`data/synonyms.json`), then
   re-classification.

## Benchmark

`corpus/` holds nine with/without spec pairs: v1 omits one behavior, v2 documents it. That is 54
scenarios, 9 planted gaps and 45 documented behaviors. Expected outcomes are in `bench/ground_truth.json`,
which the scanner never reads. The benchmark uses fixed scenarios, so it tests evidence classification
separately from whether the model can invent good scenarios.

- **dev** (checkout, jobs): used to tune prompts.
- **heldout** (auth, upload, notifications): written after tuning, run once with the final prompts.
- **heldout2** (cart, webhooks, cache, export): expected outcomes committed in `d11c484` before any model
  was run on them. Written with paraphrased scenarios and distractor passages.

### Results, all 54 scenarios, one run each, same machine

| Method | Planted gaps flagged | Documented behaviors wrongly flagged |
|---|---|---|
| Gemma, `relevance` mode (default) | 6 of 9 | 2 of 45 |
| Gemma, `describe` mode | 9 of 9 | 23 of 45 |
| No-model baseline, coverage threshold 0.4 | 6 of 9 | 19 of 45 |
| No-model baseline, coverage threshold 0.5 | 9 of 9 | 32 of 45 |

"Flagged" means Not established or Partially answered. By split:

| Split | `relevance`: gaps / false alarms | `describe`: gaps / false alarms |
|---|---|---|
| dev (12 scenarios) | 1 of 2 / 0 of 10 | 2 of 2 / 3 of 10 |
| heldout (18) | 3 of 3 / 0 of 15 | 3 of 3 / 8 of 15 |
| heldout2 (24) | 2 of 4 / 2 of 20 | 4 of 4 / 12 of 20 |

- **It is a dial, not a winner.** `relevance` mode rarely cries wolf but misses a third of the planted
  gaps. `describe` mode caught every planted gap but flagged about half of the documented behaviors.
  `describe` is also about 1.7 times slower (heldout2: 35 minutes against 20).
- **What Gemma adds over word matching.** At the same 6 of 9 recall, the baseline wrongly flags 19 of 45
  and `relevance` mode flags 2. The baseline is a simple rule and says nothing about stronger retrieval.
- **Strict metric (Not established only).** `relevance` found 3 of 9 planted gaps this way, `describe`
  6 of 9. Gemma often labels an omission "Partially answered", because the docs cover the topic and only
  miss the case. The "unresolved" metric used above was defined after the first run.
- JSON from the model was valid in every run (for example 64/64, 52/52 and 120/120 calls). Citations were
  found in the cited text in 34/34 (dev and heldout) and 26/26 (heldout2) in the `relevance` runs.
- Two runs on the same machine gave identical results (30/30 on dev and heldout). That shows determinism
  on one machine, not robustness across machines or models.

The counts are small. One miss moves a percentage a lot, so read the counts.

### Failures and caveats

- **Missed gaps in `relevance` mode:** jobs J1 (dev), cart K1 and webhooks W1 (heldout2). In each, the
  v1 spec lacked the behavior and Gemma called the scenario Answered. For J1 it cited the sentence about
  retrying a job that raises an error, as proof of recovery after a worker crash. The citation was real, but
  the inference was not. The citation check cannot catch this, and the `relevance` check did not.
- **False alarms in `relevance` mode:** export E3, in both versions, on heldout2. I wrote that scenario
  ("a client asks for the file before it is built") and its expected answer before running; it is arguably
  ambiguous. I left the ground truth unchanged.
- **`describe` mode** catches J1, cart K1 and webhooks W1, but at the cost of many false alarms (see the table).
  The default stays `relevance`.
- **Selection caveat.** `describe` mode was added after the J1 failure and measured on all three splits.
  I did not pick a winner from those numbers, and nothing was tuned afterward. Treat both modes as options.
- **Tuning history.** The first full run on the dev pairs found 0 of 2 planted gaps. I then added the
  relevance check, the partial-answer reporting and the unresolved metric, using only the dev pairs. The
  heldout pairs were run once with the final prompts. Earlier results are in `evidence/first_run_demo_output`
  (its page uses an older definition of one metric, "gaps hidden by second pass").
- **Scenario generation is weaker than classification.** On a plain `scan`, the model invents some
  requirements the spec never states. In the scheduled run on checkout/v1, one flagged "gap" was a false
  alarm (the spec does define behavior on a gateway 500), and the lost-response retry scenario was not
  generated. Treat generated scenarios as prompts for review, not as findings.
- Not compared against closed models. Markdown and text only. No contradiction case in the corpus.

## Offline and scheduled use

- The engine blocks non-loopback network connections and DNS lookups inside its own process, and refuses
  any model host that is not localhost (see `tests/test_core.py`, class `Offline`). That covers the Python
  process only, not the Ollama installation.
- Offline run: Wi-Fi off, `ping google.com` failing, then `demo --quick` completed with the same result. See
  `evidence/dark-matter-engine.mp4` and `evidence/offline_results.png`.
- Scheduled run: a Windows Task Scheduler task ran by itself at 2:00 AM (last result 0) and wrote the report
  and log within 2 seconds, reusing the saved result because the docs had not changed. The first scan of
  one spec took about 8.5 minutes. See `evidence/last_run.log` and `evidence/last_run_2am.log`. The overnight
  run needs the laptop awake and Ollama running. Task Scheduler blocks starting on battery by default; I
  changed that setting by hand for this test.

## Layout

```
dark_matter.py   CLI: scan, schedule, demo, bench, baseline, compare
dme/             index, retrieve, model (Ollama), validate, pipeline, report, guard, baseline
data/            synonym groups (hand-written)
corpus/          nine with/without spec pairs
bench/           scenarios, ground truth (never read by the scanner), benchmark runner
evidence/        recordings, logs, result pages and the compare output from the runs above
tests/           unit tests (stub model)
```

`--fake` runs a stub model. Those numbers check the harness only and say nothing about Gemma.

MIT licensed.
