import json
import socket
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dark_matter
from dme import guard, report
from dme.index import build_index
from dme.model import ModelError, OllamaModel
from dme.pipeline import analyze
from dme.retrieve import Retriever, load_synonyms
from dme.testing import FakeModel
from dme.validate import (ANSWERED, CONTRADICTED, NOT_ESTABLISHED, UNVERIFIED, locate_citation,
                          verify)

SYN = load_synonyms(ROOT / "data/synonyms.json")
FIXED = json.loads((ROOT / "bench/fixed_scenarios.json").read_text())


def scan(proj, ver, model=None, **kw):
    return analyze(model or FakeModel(), ROOT / "corpus" / proj / ver, SYN, FIXED[proj], **kw)


def status(res, sid):
    return next(f for f in res["findings"] if f["id"] == sid)["status"]


class Validator(unittest.TestCase):
    def setUp(self):
        self.passages, _ = build_index(ROOT / "corpus/checkout/v2")

    def test_hallucinated_citation_becomes_unverified(self):
        r = verify({"status": ANSWERED, "open_question": "",
                    "citations": [{"text": "The service guarantees exactly-once billing always"}]}, self.passages)
        self.assertEqual(r["status"], UNVERIFIED)

    def test_citation_tolerates_whitespace_and_gives_lines(self):
        loc = locate_citation("never   charges the order\na second time", self.passages)
        self.assertIsNotNone(loc)
        self.assertEqual(loc["file"], "spec.md")
        self.assertGreater(loc["line_start"], 10)

    def test_contradiction_needs_two_passages(self):
        c = {"text": "returns 402 with the decline reason"}
        r = verify({"status": CONTRADICTED, "citations": [c], "open_question": ""}, self.passages)
        self.assertEqual(r["status"], UNVERIFIED)

    def test_not_established_needs_no_citation(self):
        r = verify({"status": NOT_ESTABLISHED, "citations": [], "open_question": ""}, self.passages)
        self.assertEqual(r["status"], NOT_ESTABLISHED)


class Retrieval(unittest.TestCase):
    def test_synonym_expansion_adds_terms(self):
        passages, _ = build_index(ROOT / "corpus/jobs/v2")
        self.assertIn("lease", Retriever(passages, SYN).expansion_terms("a worker crashes"))

    def test_index_keeps_line_numbers(self):
        passages, _ = build_index(ROOT / "corpus/checkout/v1")
        self.assertEqual(passages[1].heading, "Initiating payment")
        self.assertEqual(passages[1].start_line, 3)


class Pipeline(unittest.TestCase):
    def test_omission_flagged_and_fix_recognized(self):
        self.assertEqual(status(scan("checkout", "v1"), "C1"), NOT_ESTABLISHED)
        self.assertEqual(status(scan("checkout", "v2"), "C1"), ANSWERED)
        self.assertEqual(status(scan("jobs", "v1"), "J1"), NOT_ESTABLISHED)
        self.assertEqual(status(scan("jobs", "v2"), "J1"), ANSWERED)

    def test_documented_behavior_not_flagged(self):
        # cart K1 is a deliberate paraphrase ("leaves without paying" vs "not checked out within
        # 30 minutes"): lexical retrieval misses it before any model is involved. Kept as a hard case.
        known_retrieval_miss = {("cart", "K1")}
        for proj in FIXED:
            res = scan(proj, "v2")
            flagged = {(proj, f["id"]) for f in res["findings"] if f["status"] == NOT_ESTABLISHED}
            self.assertEqual(flagged - known_retrieval_miss, set())

    def test_bad_model_output_is_unverified_not_a_gap(self):
        class Bad:
            def info(self): return {"tag": "bad", "digest": None}
            def generate_json(self, s, u): raise ModelError("garbage")
        res = scan("checkout", "v2", Bad())
        self.assertTrue(all(f["status"] == UNVERIFIED for f in res["findings"]))
        self.assertGreater(res["stats"]["invalid_json"], 0)

    def test_fake_citation_downgraded(self):
        class Liar(FakeModel):
            def generate_json(self, s, u):
                return {"status": "Answered", "citations": [{"file": "x", "text": "totally invented sentence here"}]}
        res = scan("checkout", "v2", Liar())
        self.assertTrue(all(f["status"] == UNVERIFIED for f in res["findings"]))


class Relevance(unittest.TestCase):
    def test_irrelevant_citation_downgrades_answered_to_not_established(self):
        res = scan("checkout", "v2", FakeModel(relevance=False))
        self.assertTrue(all(f["status"] == NOT_ESTABLISHED for f in res["findings"]))
        self.assertTrue(all(f["pass_used"] == 2 for f in res["findings"]))

    def test_relevant_citation_stays_answered(self):
        self.assertEqual(status(scan("checkout", "v2"), "C1"), ANSWERED)

    def test_report_shows_partial_section(self):
        res = scan("checkout", "v1")
        res["findings"][1]["status"] = "Partially answered"
        self.assertIn("Partially answered or contradicted", report.render(res))


class DescribeMode(unittest.TestCase):
    def test_describe_mode_downgrades_when_situations_differ(self):
        res = scan("checkout", "v2", FakeModel(relevance=False), verify_mode="describe")
        self.assertTrue(all(f["status"] == NOT_ESTABLISHED for f in res["findings"]))

    def test_describe_mode_keeps_matching_answers(self):
        res = scan("checkout", "v2", verify_mode="describe")
        self.assertEqual(status(res, "C1"), ANSWERED)
        self.assertEqual(res["verify_mode"], "describe")

    def test_none_mode_skips_the_check(self):
        res = scan("checkout", "v2", FakeModel(relevance=False), verify_mode="none")
        self.assertEqual(status(res, "C1"), ANSWERED)


class Compare(unittest.TestCase):
    def tearDown(self):
        guard.uninstall()

    def test_compare_writes_one_file_per_arm_with_scenario_detail(self):
        import argparse
        import tempfile
        d = Path(tempfile.mkdtemp())
        a = argparse.Namespace(out_dir=str(d), only=None, model="x", host="", fake=True)
        self.assertEqual(dark_matter.cmd_compare(a), 0)
        names = sorted(p.name for p in d.iterdir())
        self.assertEqual(names, ["describe_dev.json", "describe_heldout.json",
                                 "describe_heldout2.json", "relevance_heldout2.json"])
        detail = json.loads((d / "relevance_heldout2.json").read_text())["detail"]
        self.assertEqual(len(detail), 24)
        self.assertIn("cited", detail[0])


class Baseline(unittest.TestCase):
    def test_baseline_runs_without_a_model_and_reports_every_threshold(self):
        from bench.run_bench import run_baseline
        r = run_baseline()
        self.assertEqual(r["n_scenarios"], 54)
        self.assertEqual(len(r["by_threshold"]), 5)

    def test_new_pairs_are_pre_registered(self):
        gt = json.loads((ROOT / "bench/ground_truth.json").read_text())["items"]
        h2 = [i for i in gt if i["split"] == "heldout2"]
        self.assertEqual(len(h2), 24)
        self.assertEqual(sum(i["expected"] == NOT_ESTABLISHED for i in h2), 4)


class Consistency(unittest.TestCase):
    def test_every_fixed_scenario_has_ground_truth_and_a_planted_section(self):
        gt = json.loads((ROOT / "bench/ground_truth.json").read_text())["items"]
        keys = {(i["project"], i["scenario_id"]) for i in gt}
        for proj, scs in FIXED.items():
            for s in scs:
                self.assertIn((proj, s["id"]), keys)
            v1 = (ROOT / "corpus" / proj / "v1" / "spec.md").read_text()
            v2 = (ROOT / "corpus" / proj / "v2" / "spec.md").read_text()
            self.assertTrue(v2.startswith(v1.rstrip()))
            self.assertGreater(len(v2), len(v1))

    def test_placeholder_question_falls_back(self):
        class Echo(FakeModel):
            def generate_json(self, s, u):
                out = super().generate_json(s, u)
                if "status" in out:
                    out["open_question"] = "the specific question an engineer must resolve"
                return out
        res = scan("checkout", "v1", Echo())
        self.assertTrue(all("payment" in f["open_question"].lower() or "card" in f["open_question"].lower()
                            or "gateway" in f["open_question"].lower() for f in res["findings"]))


class Offline(unittest.TestCase):
    def tearDown(self):
        guard.uninstall()

    def test_pipeline_runs_with_non_loopback_blocked(self):
        guard.install()
        self.assertEqual(status(scan("checkout", "v1"), "C1"), NOT_ESTABLISHED)
        with self.assertRaises(guard.BlockedConnection):
            socket.create_connection(("93.184.216.34", 80), timeout=1)
        with self.assertRaises(guard.BlockedConnection):
            socket.getaddrinfo("example.com", 80)

    def test_model_refuses_remote_host(self):
        with self.assertRaises(ModelError):
            OllamaModel("gemma3:4b", host="http://example.com:11434")


class Scheduling(unittest.TestCase):
    def test_schedule_invokes_scan_command(self):
        cmd = dark_matter.schedule_command("./docs", "02:00", "out/latest.html")
        self.assertIn(" scan ", cmd)
        self.assertIn("dark_matter.py", cmd)

    def test_windows_task_command_fits_schtasks_limit(self):
        long_root = "C:/Users/Admin/PycharmProjects/pythonProject/dark-matter-engine/" + "x" * 120
        args, wrapper, text = dark_matter.windows_schedule_plan(long_root, "02:00", long_root + "/out/latest.html")
        tr = args[args.index("/TR") + 1]
        self.assertLess(len(tr), 261)
        self.assertIn(" scan ", text)
        self.assertIn("last_run.log", text)

    def test_power_fix_allows_battery_start(self):
        self.assertIn("DisallowStartIfOnBatteries = $false", dark_matter.POWERSHELL_FIX)
        self.assertIn("StartWhenAvailable = $true", dark_matter.POWERSHELL_FIX)

    def test_failed_scan_writes_failure_report(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "r" / "latest.html"
        empty = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            dark_matter.run_scan(empty, FakeModel(), out, synonyms=[])
        self.assertIn("scan FAILED", out.read_text())

    def test_report_renders_and_caches(self):
        import tempfile
        out = Path(tempfile.mkdtemp()) / "latest.html"
        r1 = dark_matter.run_scan(ROOT / "corpus/checkout/v1", FakeModel(), out, synonyms=SYN)
        r2 = dark_matter.run_scan(ROOT / "corpus/checkout/v1", FakeModel(), out, synonyms=SYN)
        self.assertTrue(r2.get("cached"))
        self.assertIn("potential gaps", out.read_text())


class Demo(unittest.TestCase):
    def tearDown(self):
        guard.uninstall()

    def test_demo_command_writes_one_results_page(self):
        import argparse
        import tempfile
        d = Path(tempfile.mkdtemp())
        a = argparse.Namespace(out_dir=str(d), runs=1, model="x", host="", fake=True, quick=False)
        self.assertEqual(dark_matter.cmd_demo(a), 0)
        page = (d / "index.html").read_text()
        self.assertIn("v1 (omission) vs v2", page)
        self.assertIn("NOT model results", page)
        self.assertTrue((d / "checkout_v1" / "latest.html").exists())
        self.assertTrue((d / "benchmark.json").exists())


if __name__ == "__main__":
    unittest.main()
