#!/usr/bin/env python3
"""Runs every fixture in test/fixtures through hooks/done_check.py.
Usage: python3 test/run.py [name-substring]"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(os.path.dirname(HERE), "hooks", "done-check.sh")
FIX = os.path.join(HERE, "fixtures")


def run(name):
    d = os.path.join(FIX, name)
    exp = json.load(open(os.path.join(d, "expect.json"), encoding="utf-8"))
    tmp = tempfile.mkdtemp(prefix="dc-")
    try:
        root = os.path.join(tmp, "proj")
        shutil.copytree(os.path.join(d, "repo"), root)
        os.makedirs(os.path.join(root, ".git"))
        tr = open(os.path.join(d, "transcript.jsonl"), encoding="utf-8").read().replace("__ROOT__", root)
        tpath = os.path.join(tmp, "t.jsonl")
        open(tpath, "w", encoding="utf-8").write(tr)
        payload = {"session_id": "fixture", "transcript_path": tpath, "cwd": root,
                   "hook_event_name": "Stop", "stop_hook_active": False}
        payload.update(exp.get("payload", {}))
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DONE_CHECK", "CLAUDE_PLUGIN_OPTION_"))}
        env.update(exp.get("env", {}))
        p = subprocess.run(["sh", HOOK], input=json.dumps(payload), capture_output=True, text=True, env=env,
                           cwd=root, timeout=30)
        out = json.loads(p.stdout) if p.stdout.strip() else {}
        got = "block" if out.get("decision") == "block" else "pass"
        errs = []
        if p.returncode != 0:
            errs.append("exit %d" % p.returncode)
        if p.stderr.strip():
            errs.append("stderr: " + p.stderr.strip()[:200])
        if got != exp["decision"]:
            errs.append("want %s got %s" % (exp["decision"], got))
        if exp.get("reason_contains") and exp["reason_contains"] not in out.get("reason", ""):
            errs.append("reason lacks %r" % exp["reason_contains"])
        if exp.get("message_contains") and exp["message_contains"] not in out.get("systemMessage", ""):
            errs.append("message lacks %r" % exp["message_contains"])
        return errs, out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    names = sorted(n for n in os.listdir(FIX) if flt in n)
    bad = 0
    for n in names:
        errs, out = run(n)
        if errs:
            bad += 1
            print("FAIL %s: %s | %s" % (n, "; ".join(errs), json.dumps(out, ensure_ascii=False)[:300]))
        else:
            print("ok   %s" % n)
    print("\n%d/%d fixtures passed" % (len(names) - bad, len(names)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
