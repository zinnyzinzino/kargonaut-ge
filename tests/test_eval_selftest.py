"""The eval's self-test (evals/selftest.py) as a test: a scripted fake Gemini, no key, no quota.

Proves every case in evals/cases.json is passable with the demo data's real numbers, and that the grader catches
the mistakes the cases were written for. Gemini's own judgement is measured by evals/run_eval.py, by hand.
"""
import os
import subprocess
import sys

from conftest import ROOT


def test_eval_selftest():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "GEMINI_API_KEY": "fake-key-for-selftest"}
    env.pop("KARGONAUT_DB", None)   # the eval makes its own sandbox database
    run = subprocess.run([sys.executable, str(ROOT / "evals" / "selftest.py")], capture_output=True, text=True,
                         encoding="utf-8", env=env, cwd=ROOT, timeout=600)
    assert run.returncode == 0 and "Self-test OK" in run.stdout, run.stdout[-3000:] + run.stderr[-2000:]
