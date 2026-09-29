#!/usr/bin/env python3
"""AF-7a's own acceptance test for the runner's mechanics (not the live clusters): a step whose
verify exits 0 is reported PASS, one that exits non-zero is FAIL and the overall exit code is 1,
and --render produces the command/expected text without running anything. Live-cluster proof that
a real walkthrough replays green lives in docs/walkthroughs/*.yaml themselves, run by hand against
kiac-dev/kind-prod - this test never touches a real cluster.

    python3 tools/test_walkthrough_runner.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = str(ROOT / "tools" / "walkthrough-runner")

FIXTURE = """\
title: "Fixture walkthrough"
sourceDoc: nowhere.md
steps:
  - id: passes
    title: a step that passes
    command: "echo hi"
    expected: "hi"
    verify: "true"
  - id: fails
    title: a step that fails
    command: "false"
    expected: "never"
    verify: "false"
"""

ALL_PASS = """\
title: "All-pass fixture"
steps:
  - id: a
    title: a
    command: "echo a"
    expected: "a"
    verify: "true"
"""


def run(*args):
    return subprocess.run([sys.executable, RUNNER, *args], capture_output=True, text=True, cwd=ROOT)


def main():
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        mixed = Path(td) / "mixed.yaml"
        mixed.write_text(FIXTURE)
        r = run(str(mixed))
        if "PASS passes" not in r.stdout:
            print("FAIL: passing step not reported PASS"); failed = 1
        if "FAIL fails" not in r.stdout:
            print("FAIL: failing step not reported FAIL"); failed = 1
        if r.returncode != 1:
            print(f"FAIL: exit code should be 1 with a failing step, got {r.returncode}"); failed = 1
        if "1/2 steps passed" not in r.stdout:
            print("FAIL: summary line wrong"); failed = 1

        allpass = Path(td) / "allpass.yaml"
        allpass.write_text(ALL_PASS)
        r = run(str(allpass))
        if r.returncode != 0:
            print(f"FAIL: exit code should be 0 with no failing steps, got {r.returncode}"); failed = 1
        if "replays green" not in r.stdout:
            print("FAIL: all-pass run should say 'replays green'"); failed = 1

        rendered = Path(td) / "out.md"
        r = run(str(mixed), "--render", str(rendered))
        if r.returncode != 0:
            print("FAIL: --render should exit 0"); failed = 1
        text = rendered.read_text()
        if "echo hi" not in text or "**Expected:** hi" not in text:
            print("FAIL: rendered markdown missing command/expected text"); failed = 1
        if "a step that fails" not in text:
            print("FAIL: rendering should document every step, including ones that would fail"); failed = 1

    if failed:
        print("FAILED")
        return 1
    print("ok: walkthrough-runner mechanics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
