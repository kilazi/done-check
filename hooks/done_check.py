#!/usr/bin/env python3
"""done-check: a Claude Code Stop hook.

Blocks the stop ONCE when the agent's final message claims the work is done
(done, fixed, works, passing, ...) after it edited code, but the repo's verify
command did not run and pass after the last code edit. A second stop in the
same turn (stop_hook_active) always goes through, so it can never trap a session.

Python 3 standard library only. Reads the Stop hook JSON on stdin, writes the
decision JSON on stdout, always exits 0 (any internal error = let go).
"""
import json
import os
import re
import shlex
import sys
import time

DOC_EXT = {".md", ".mdx", ".markdown", ".txt", ".rst", ".adoc"}
DOC_NAMES = re.compile(r"^(license|licence|copying|notice|authors|contributors|changelog|changes|history|release[-_ ]?notes?|releases)(\.[a-z0-9]+)?$", re.I)
DOC_DIRS = {"docs", "doc"}

CLAIM = re.compile(
    r"\b(done|fixed|fixes|works|working|passing|passes|passed|green|complete|completed|implemented|resolved|"
    r"all set|ready to (merge|ship|review)|shipped)\b"
    r"|\b(listo|arreglad[oa]|funciona|hecho|terminad[oa]|resuelto|corregid[oa])\b"
    r"|完了|修正しました|直りました|動作します|完成|已修复|修好|已完成|搞定",
    re.I)
NEGATED = re.compile(
    r"\b(not|n't|never|no longer|isn't|aren't|wasn't|haven't|hasn't|still not|not yet)\s+(\w+\s+){0,2}?"
    r"(done|fixed|working|passing|complete|completed|resolved|green)\b"
    r"|\bno\s+(funciona|est[aá] listo)\b",
    re.I)

FAIL_MARKERS = re.compile(
    r"(^|\s)FAIL(\s|:|$)|\bFAILED\b|\bfailures?\b(?!\s*[:=]?\s*0\b)|\bfailed\b|Error:|panicked|npm ERR!"
    r"|short test summary|\berror\(s\)|\b[1-9]\d* errors?\b",
    re.M)
ZERO_FAIL = re.compile(r"\b0 (failed|failures?|errors?)\b|\bfailed[:=]\s*0\b|\bfailures[:=]\s*0\b", re.I)

FAILNAME_PATTERNS = [
    re.compile(r"^FAILED\s+(\S+)", re.M),                       # pytest short summary
    re.compile(r"^\s*(?:FAIL|✗|×)\s+(\S+\.(?:test|spec)\.\S+)", re.M),  # jest / vitest file
    re.compile(r"^---\s+FAIL:\s+(\S+)", re.M),                   # go
    re.compile(r"^test\s+(\S+)\s+\.\.\.\s+FAILED", re.M),        # cargo
    re.compile(r"^\s*rspec\s+(\./\S+)", re.M),                   # rspec
]

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SEG_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")


# ---------------------------------------------------------------- utilities

def emit(obj):
    if obj:
        sys.stdout.write(json.dumps(obj))
    sys.exit(0)


def off(val):
    return str(val or "").strip().lower() in {"off", "0", "false", "no", "disabled"}


def read_lines(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def find_root(cwd):
    d = os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(cwd)
        d = parent


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                out.append(c.get("text", ""))
        return "\n".join(out)
    return ""


# ---------------------------------------------------------------- transcript

def parse_transcript(path):
    """Return (events, last_text, last_is_assistant). events in order:
    ("edit", path, idx) and ("bash", command, cwd, output, failed, idx)."""
    entries = []
    for line in read_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    uses = {}
    order = []
    last_text, last_is_assistant = "", False
    for i, e in enumerate(entries):
        if e.get("isSidechain"):
            continue
        typ = e.get("type")
        msg = e.get("message") or {}
        content = msg.get("content")
        if typ == "assistant" and isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            has_tool = any(isinstance(c, dict) and c.get("type") == "tool_use" for c in content)
            if texts:
                last_text, last_is_assistant = "\n".join(texts), True
            elif has_tool:
                last_is_assistant = False
            for c in content:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    uses[c.get("id")] = {"name": c.get("name"), "input": c.get("input") or {},
                                         "cwd": e.get("cwd"), "idx": i}
                    order.append(c.get("id"))
        elif typ == "user":
            if isinstance(content, str) or (isinstance(content, list) and any(
                    isinstance(c, dict) and c.get("type") == "text" for c in content)):
                last_is_assistant = False
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        u = uses.get(c.get("tool_use_id"))
                        if u is not None:
                            u["result"] = result_text(c.get("content"))
                            u["is_error"] = bool(c.get("is_error"))
                            u["ridx"] = i
                            tur = e.get("toolUseResult")
                            if isinstance(tur, dict) and tur.get("interrupted"):
                                u["is_error"] = True
    events = []
    for uid in order:
        u = uses[uid]
        name, inp = u["name"], u["input"]
        if name in WRITE_TOOLS:
            p = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
            if p:
                events.append(("edit", p, u["cwd"], u["idx"]))
        elif name == "Bash":
            cmd = inp.get("command") or ""
            for p in bash_written_paths(cmd):
                events.append(("edit", p, u["cwd"], u["idx"]))
            if "result" in u:
                out = u["result"]
                m = re.match(r"\s*Exit code (\d+)", out)
                failed = u.get("is_error", False) or bool(m and m.group(1) != "0")
                events.append(("bash", cmd, u["cwd"], out, failed, u.get("ridx", u["idx"])))
    return events, last_text, last_is_assistant


REDIRECT = re.compile(r"(?<![0-9&<>])>{1,2}\s*([^\s;&|<>()]+)")
TEE = re.compile(r"\btee\s+(?:-a\s+)?([^\s;&|<>()]+)")
SED_I = re.compile(r"\b(?:sed|perl)\s+(?:-[a-zA-Z]*i[a-zA-Z.]*\S*)(?:\s+-e)?\s+(?:'[^']*'|\"[^\"]*\"|\S+)\s+([^\s;&|<>()]+)")


def bash_written_paths(cmd):
    out = []
    for rx in (REDIRECT, TEE, SED_I):
        for m in rx.finditer(cmd):
            p = m.group(1).strip("'\"")
            if not p or p.startswith("&") or p.startswith("/dev/") or p.startswith("$"):
                continue
            out.append(p)
    return out


# ---------------------------------------------------------------- repo config

def repo_settings(root):
    """Returns dict: verify (str|None), off (bool), baseline (str|None)."""
    s = {"verify": None, "off": False, "baseline": None}
    dc = os.path.join(root, ".done-check")
    if os.path.isfile(dc):
        for line in read_lines(dc):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, sep, v = line.partition(":")
            k = k.strip().lower()
            if sep and k in ("verify", "baseline"):
                v = v.strip().strip("`")
                if k == "verify":
                    if off(v):
                        s["off"] = True
                    else:
                        s["verify"] = v
                else:
                    s["baseline"] = v.lower()
            elif off(line):
                s["off"] = True
            elif s["verify"] is None:
                s["verify"] = line.strip("`")
    if s["verify"] is None and not s["off"]:
        for line in read_lines(os.path.join(root, "AGENTS.md")):
            m = re.match(r"^\s*(?:[-*]\s*)?\**verify\**\s*:\s*(.+?)\s*$", line, re.I)
            if m:
                v = m.group(1).strip().strip("`").strip()
                if off(v):
                    s["off"] = True
                else:
                    s["verify"] = v
                break
    return s


def is_doc(path):
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1].lower()
    if ext in DOC_EXT or DOC_NAMES.match(base):
        return True
    parts = [p.lower() for p in path.replace("\\", "/").split("/")]
    return any(p in DOC_DIRS for p in parts[:-1])


def pkg_runner(d, root):
    for dd in (d, root):
        if os.path.exists(os.path.join(dd, "pnpm-lock.yaml")):
            return "pnpm"
        if os.path.exists(os.path.join(dd, "yarn.lock")):
            return "yarn"
        if os.path.exists(os.path.join(dd, "bun.lock")) or os.path.exists(os.path.join(dd, "bun.lockb")):
            return "bun"
    return "npm"


def npm_script(d, names=("test", "build")):
    pj = load_json(os.path.join(d, "package.json"))
    if not isinstance(pj, dict):
        return None
    scripts = pj.get("scripts") or {}
    for n in names:
        body = scripts.get(n)
        if not body:
            continue
        if n == "test" and "no test specified" in body:
            continue
        return n, body, pj.get("name") or os.path.basename(d)
    return None


def is_monorepo(root):
    pj = load_json(os.path.join(root, "package.json")) or {}
    return bool(isinstance(pj, dict) and pj.get("workspaces")) or any(
        os.path.exists(os.path.join(root, f)) for f in ("pnpm-workspace.yaml", "turbo.json", "nx.json", "lerna.json"))


def file_has(path, rx):
    return any(re.search(rx, line) for line in read_lines(path))


def detect(root, scope):
    """Detect the verify command for a scope dir. Returns dict or None:
    kind, display, and matcher data."""
    rs = repo_settings(root)
    if rs["verify"]:
        return {"kind": "custom", "cmd": rs["verify"], "display": rs["verify"]}
    for d in ([scope, root] if scope != root else [root]):
        sc = npm_script(d)
        if sc:
            name, body, pkg = sc
            r = pkg_runner(d, root)
            disp = ("%s test" % r) if name == "test" else ("%s run build" % r)
            rel = os.path.relpath(d, root)
            if rel != ".":
                disp = "cd %s && %s" % (rel, disp)
            return {"kind": "npm", "script": name, "body": body, "dir": d, "pkg": pkg, "display": disp}
    mk = os.path.join(root, "Makefile")
    if os.path.isfile(mk) and file_has(mk, r"^test\s*:"):
        return {"kind": "make", "display": "make test"}
    if any(os.path.exists(os.path.join(root, f)) for f in ("pyproject.toml", "pytest.ini", "setup.cfg", "tests")) \
            or os.path.isdir(os.path.join(root, "tests")):
        return {"kind": "pytest", "display": "pytest"}
    if os.path.isfile(os.path.join(root, "Cargo.toml")):
        return {"kind": "cargo", "display": "cargo test"}
    if os.path.isfile(os.path.join(root, "go.mod")):
        return {"kind": "go", "display": "go test ./..."}
    jf = os.path.join(root, "justfile")
    if os.path.isfile(jf) and file_has(jf, r"^test\b.*:"):
        return {"kind": "just", "display": "just test"}
    for dj in ("deno.json", "deno.jsonc"):
        p = os.path.join(root, dj)
        if os.path.isfile(p) and file_has(p, r'"test"\s*:'):
            return {"kind": "deno", "display": "deno task test"}
    if os.path.isfile(os.path.join(root, "mix.exs")):
        return {"kind": "mix", "display": "mix test"}
    gf = os.path.join(root, "Gemfile")
    if os.path.isfile(gf) and file_has(gf, r"rspec"):
        return {"kind": "rspec", "display": "bundle exec rspec"}
    return None


# ---------------------------------------------------------------- matching

ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPERS = {"time", "command", "nohup", "env", "exec"}


def split_segments(cmd):
    """Split a shell command into (segment_text, piped, position, total) tuples."""
    segs = [s for s in SEG_SPLIT.split(cmd.strip()) if s.strip()]
    out = []
    for i, s in enumerate(segs):
        # a single | (not ||) means a pipe
        parts = re.split(r"(?<!\|)\|(?!\|)", s)
        out.append((parts[0].strip(), len(parts) > 1, i, len(segs)))
    return out


def tokens(seg):
    try:
        t = shlex.split(seg)
    except ValueError:
        t = seg.split()
    while t and (ENV_ASSIGN.match(t[0]) or t[0] in WRAPPERS or t[0] == "sudo"):
        t = t[1:]
    if len(t) >= 2 and t[0] == "timeout":
        t = t[2:]
    return t


def norm(s):
    return " ".join(tokens(s))


PM = {"npm", "pnpm", "yarn", "bun"}


def npm_invocation(t, script):
    """Is this token list `<pm> [run] <script>` (any extra args)? Returns (True, filter) where
    filter is a workspace/package name if one was given, '*' for all workspaces, None for local."""
    if not t or t[0] not in PM:
        return False, None
    pm, rest = t[0], t[1:]
    flt = None
    # pull workspace / filter flags out
    clean = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-w", "--workspace", "--filter", "-F") and i + 1 < len(rest):
            flt = rest[i + 1]
            i += 2
            continue
        m = re.match(r"^--(?:workspace|filter)=(.+)$", a)
        if m:
            flt = m.group(1)
            i += 1
            continue
        if a in ("-r", "--recursive", "--workspaces", "-ws"):
            flt = "*"
            i += 1
            continue
        clean.append(a)
        i += 1
    if pm == "yarn" and clean[:1] == ["workspace"] and len(clean) >= 2:
        flt, clean = clean[1], clean[2:]
    if pm == "yarn" and clean[:2] == ["workspaces", "foreach"]:
        flt = "*"
        clean = [c for c in clean[2:] if not c.startswith("-")]
    if clean[:1] in (["run"], ["run-script"]):
        clean = clean[1:]
    if not clean:
        return False, None
    if clean[0] == script or (script == "test" and clean[0] == "t" and pm == "npm"):
        return True, flt
    return False, None


def monorepo_runner(t, script):
    """turbo / nx forms. Returns (True, filter) like npm_invocation."""
    if t and t[0] in ("npx", "pnpx", "bunx") or t[:2] in (["pnpm", "exec"], ["yarn", "dlx"], ["pnpm", "dlx"]):
        t = t[2:] if t[0] in ("pnpm", "yarn") else t[1:]
    if not t:
        return False, None
    if t[0] == "turbo":
        rest = t[1:]
        if rest[:1] == ["run"]:
            rest = rest[1:]
        if script in rest:
            flt = "*"
            for i, a in enumerate(rest):
                if a == "--filter" and i + 1 < len(rest):
                    flt = rest[i + 1]
                elif a.startswith("--filter="):
                    flt = a.split("=", 1)[1]
            return True, flt
    if t[0] == "nx":
        rest = t[1:]
        if rest[:1] == [script] and len(rest) >= 2:
            return True, rest[1]
        if rest[:1] in (["affected"], ["run-many"]):
            for i, a in enumerate(rest):
                if a in ("-t", "--target", "--targets") and i + 1 < len(rest) and script in rest[i + 1].split(","):
                    return True, "*"
                if re.match(r"^--targets?=", a) and script in a.split("=", 1)[1].split(","):
                    return True, "*"
        if rest[:1] == ["run"] and len(rest) >= 2 and rest[1].endswith(":" + script):
            return True, rest[1].rsplit(":", 1)[0]
    return False, None


def filter_covers(flt, scope, root, pkgname):
    if flt == "*" or flt is None:
        return True
    f = flt.strip("'\"").rstrip("/").lstrip("./")
    f = re.sub(r"\.\.\.$", "", f).strip("{}")
    rel = os.path.relpath(scope, root)
    if f in (pkgname, os.path.basename(scope), rel) or f == pkgname.split("/")[-1]:
        return True
    if "*" in f:
        import fnmatch
        return fnmatch.fnmatch(pkgname, f) or fnmatch.fnmatch(rel, f)
    return False


def run_matches(det, cmd, run_cwd, scope, root):
    """Does this Bash command run the detected verify command for this scope?
    Returns (matched, trusted_exit, scoped)."""
    segs = split_segments(cmd)
    cwd = os.path.abspath(run_cwd or root)
    has_pipefail = bool(re.search(r"set\s+-[a-z]*o\s+pipefail|set\s+-o\s+pipefail|pipefail", cmd))
    or_true = bool(re.search(r"\|\|\s*(true|:|exit 0)\b", cmd))
    joined_norm = " && ".join(norm(s[0]) for s in segs)
    for text, piped, pos, total in segs:
        t = tokens(text)
        if not t:
            continue
        if t[0] == "cd" and len(t) >= 2:
            nd = os.path.expanduser(t[1])
            cwd = os.path.abspath(os.path.join(cwd, nd))
            continue
        if t[0] == "pushd" and len(t) >= 2:
            cwd = os.path.abspath(os.path.join(cwd, t[1]))
            continue
        ok, scoped = match_one(det, t, cwd, scope, root, joined_norm)
        if ok:
            trusted = not (piped and not has_pipefail) and not or_true and (pos == total - 1 or "&&" in cmd)
            return True, trusted, scoped
    return False, True, False


def match_one(det, t, cwd, scope, root, joined_norm):
    k = det["kind"]
    line = " ".join(t)
    if k == "custom":
        c = norm(det["cmd"])
        if line == c or line.startswith(c + " ") or joined_norm == c or joined_norm.startswith(c):
            return True, False
        return False, False
    if k == "npm":
        script, body, pkgdir = det["script"], det["body"], det["dir"]
        pkgname = det["pkg"]
        ok, flt = npm_invocation(t, script)
        if not ok:
            ok, flt = monorepo_runner(t, script)
        if ok:
            if flt is None:
                # local run: covers the scope if run in the scope dir, or in the root when the
                # root script itself is the verify (root test usually fans out in monorepos)
                if cwd == scope or cwd == pkgdir:
                    return True, False
                if cwd == root and (pkgdir == root or npm_script(root, (script,))):
                    return True, False
                return False, False
            return filter_covers(flt, scope, root, pkgname_for(scope, pkgname)), False
        # raw script body, or the body through npx / pnpm exec / yarn / bunx
        b = norm(body)
        cand = t
        if cand[:1] and cand[0] in ("npx", "pnpx", "bunx"):
            cand = cand[1:]
        elif cand[:2] in (["pnpm", "exec"], ["yarn", "exec"], ["bun", "x"], ["npm", "exec"]):
            cand = cand[2:]
        elif cand[:1] == ["yarn"] and len(cand) > 1:
            cand = cand[1:]
        cl = " ".join(cand)
        if b and (cl == b or cl.startswith(b + " ")) and cwd in (scope, pkgdir, root):
            return True, False
        if script == "test" and t[:2] == ["bun", "test"] and cwd in (scope, pkgdir, root):
            return True, False
        return False, False
    if k == "pytest":
        u = list(t)
        if u[:2] in (["uv", "run"], ["poetry", "run"], ["pdm", "run"], ["hatch", "run"], ["pipenv", "run"]):
            u = u[2:]
        if u and re.match(r"^(\S*/)?python3?(\.\d+)?$", u[0]) and u[1:3] == ["-m", "pytest"]:
            u = u[2:]
        if u and re.match(r"^(\S*/)?(pytest|py\.test)$", u[0]):
            rest = u[1:]
            scoped = "-k" in rest or any(not a.startswith("-") for a in rest)
            return True, scoped
        return False, False
    if k == "cargo":
        return (t[:2] == ["cargo", "test"] or t[:3] == ["cargo", "nextest", "run"]), False
    if k == "go":
        return t[:2] == ["go", "test"], False
    if k == "make":
        if t and t[0] in ("make", "gmake") and "test" in t[1:]:
            return True, False
        return False, False
    if k == "just":
        return t[:2] == ["just", "test"], False
    if k == "deno":
        return t[:2] == ["deno", "test"] or t[:3] == ["deno", "task", "test"], False
    if k == "mix":
        return t[:2] == ["mix", "test"], False
    if k == "rspec":
        return t[:1] == ["rspec"] or t[:3] == ["bundle", "exec", "rspec"] or t[:2] == ["bin/rspec"], False
    return False, False


def pkgname_for(scope, fallback):
    pj = load_json(os.path.join(scope, "package.json"))
    if isinstance(pj, dict) and pj.get("name"):
        return pj["name"]
    return fallback


SPECIFIC = re.compile(r"^\s*(FAILED\s|FAIL\s|---\s+FAIL:|test\s+\S+\s+\.\.\.\s+FAILED|thread .* panicked|npm ERR!|\S*Error:)")


def failure_line(out):
    for line in out.splitlines():
        if SPECIFIC.search(line):
            return line.strip()[:200]
    for line in out.splitlines():
        if FAIL_MARKERS.search(line) and not ZERO_FAIL.search(line):
            return line.strip()[:200]
    return None


def output_failed(out):
    return failure_line(out) is not None


def failing_names(out):
    names = set()
    for rx in FAILNAME_PATTERNS:
        for m in rx.finditer(out):
            names.add(m.group(1))
    return names


# ---------------------------------------------------------------- main

def scope_of(path, root, mono):
    d = os.path.dirname(path)
    if not mono:
        return root
    while d.startswith(root) and d != root:
        if os.path.isfile(os.path.join(d, "package.json")):
            return d
        d = os.path.dirname(d)
    return root


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        emit(None)
    if off(os.environ.get("DONE_CHECK")) or off(os.environ.get("CLAUDE_PLUGIN_OPTION_ENABLED")):
        emit(None)
    if payload.get("stop_hook_active"):
        emit(None)
    cwd = payload.get("cwd") or os.getcwd()
    root = find_root(cwd)
    rs = repo_settings(root)
    if rs["off"]:
        emit(None)
    baseline_mode = (os.environ.get("CLAUDE_PLUGIN_OPTION_BASELINE") or rs["baseline"] or "ignore").strip().lower()

    tpath = payload.get("transcript_path") or ""
    final = payload.get("last_assistant_message")
    if isinstance(final, dict):
        final = result_text(final.get("content"))
    events, last_text, last_is_assistant = parse_transcript(tpath)
    if not final:
        tries = 0
        while not last_is_assistant and tries < 3:
            time.sleep(0.5)
            tries += 1
            events, last_text, last_is_assistant = parse_transcript(tpath)
        if not last_is_assistant:
            emit({"systemMessage": "done-check: could not read the final message, not checking this stop"})
        final = last_text

    if not final or not CLAIM.search(NEGATED.sub(" ", final)):
        emit(None)

    # code edits inside the repo, not docs
    edits = []
    for ev in events:
        if ev[0] != "edit":
            continue
        p = ev[1]
        if not os.path.isabs(p):
            p = os.path.join(ev[2] or cwd, p)
        p = os.path.abspath(p)
        if not (p == root or p.startswith(root + os.sep)):
            continue
        rel = os.path.relpath(p, root)
        if rel.startswith(".git" + os.sep) or rel in (".done-check",) or is_doc(rel):
            continue
        edits.append((p, ev[3]))
    if not edits:
        emit(None)

    mono = is_monorepo(root)
    scopes = {}
    for p, idx in edits:
        s = scope_of(p, root, mono)
        scopes[s] = max(scopes.get(s, -1), idx)
    first_edit = min(idx for _, idx in edits)

    runs = [ev for ev in events if ev[0] == "bash"]
    notes = []
    for scope, last_edit in sorted(scopes.items(), key=lambda kv: -kv[1]):
        det = detect(root, scope)
        if det is None:
            emit({"systemMessage": "done-check: no test command found, add `verify: <command>` to AGENTS.md"})
        baseline = None
        latest = None
        for _, cmd, rcwd, out, failed, idx in runs:
            ok, trusted, scoped = run_matches(det, cmd, rcwd, scope, root)
            if not ok:
                continue
            # exit status is trusted unless the run was piped without pipefail, masked with
            # `|| true`, or followed by another command; then the output is scanned instead
            bad = failed if trusted else output_failed(out)
            if baseline is None and idx < first_edit:
                baseline = failing_names(out) if bad else set()
            if idx > last_edit:
                latest = (cmd, out, bad, scoped)
        shown = det["display"]
        if latest is None:
            emit({"decision": "block",
                  "reason": "done-check: run `%s` before saying done (this hook lets go if you stop again)" % shown})
        cmd, out, bad, scoped = latest
        if bad:
            names = failing_names(out)
            if baseline and names and names <= baseline:
                if baseline_mode == "warn":
                    emit({"decision": "block",
                          "reason": "done-check: these failed before your edit: %s (this hook lets go if you stop again)"
                                    % ", ".join(sorted(names))})
                notes.append("done-check: only failures that were already there before the edit (%s)"
                             % ", ".join(sorted(names)))
                continue
            line = failure_line(out) or (out.strip().splitlines() or ["exit code non-zero"])[0][:200]
            emit({"decision": "block",
                  "reason": "done-check: `%s` failed after your last edit: %s (this hook lets go if you stop again)"
                            % (shown, line)})
        if scoped:
            notes.append("done-check: a scoped run counted; run the full `%s` once before you merge" % shown)
    emit({"systemMessage": notes[0]} if notes else None)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # never break a session
        sys.stderr.write("done-check: internal error, letting go (%s)\n" % exc)
        sys.exit(0)
