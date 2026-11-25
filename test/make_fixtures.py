#!/usr/bin/env python3
"""Writes the synthetic fixture suite into test/fixtures/. Every project, path and
message here is invented. Run: python3 test/make_fixtures.py"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")
R = "__ROOT__"


class T:
    """Builds a Claude Code style transcript JSONL."""

    def __init__(self, prompt="please fix the bug in the parser"):
        self.lines, self.n = [], 0
        self.add("user", prompt)

    def _id(self):
        self.n += 1
        return "toolu_%04d" % self.n

    def add(self, typ, content, cwd=R, extra=None):
        e = {"type": typ, "cwd": cwd, "sessionId": "fixture", "isSidechain": False,
             "uuid": "u%04d" % len(self.lines), "timestamp": "2030-01-01T00:00:%02dZ" % (len(self.lines) % 60),
             "message": {"role": typ, "content": content}}
        if extra:
            e.update(extra)
        self.lines.append(e)
        return self

    def tool(self, name, inp, out="ok", err=False, cwd=R):
        i = self._id()
        self.add("assistant", [{"type": "tool_use", "id": i, "name": name, "input": inp}], cwd=cwd)
        self.add("user", [{"type": "tool_result", "tool_use_id": i, "content": out, "is_error": err}], cwd=cwd,
                 extra={"toolUseResult": {"stdout": out, "stderr": "", "interrupted": False}})
        return self

    def edit(self, path, cwd=R):
        return self.tool("Edit", {"file_path": path if path.startswith("/") else R + "/" + path,
                                  "old_string": "a", "new_string": "b"}, out="The file has been updated.", cwd=cwd)

    def write(self, path):
        return self.tool("Write", {"file_path": R + "/" + path, "content": "x = 1\n"}, out="File created.")

    def bash(self, cmd, out="", code=0, cwd=R):
        if code:
            out = "Exit code %d\n%s" % (code, out)
        return self.tool("Bash", {"command": cmd, "description": "run"}, out=out, err=bool(code), cwd=cwd)

    def say(self, text):
        return self.add("assistant", [{"type": "text", "text": text}])

    def dump(self):
        return "\n".join(json.dumps(x) for x in self.lines) + "\n"


PASS_JS = "Test Files  3 passed (3)\n     Tests  12 passed (12)\n"
FAIL_JS = " FAIL  src/parse.test.js > parses dates\nAssertionError: expected 2 to be 3\n     Tests  1 failed | 11 passed (12)\n"
PASS_PY = "............ [100%]\n12 passed in 0.42s\n"
FAIL_PY = "=========================== short test summary info ============================\nFAILED tests/test_parse.py::test_dates - assert 2 == 3\n1 failed, 11 passed in 0.40s\n"
OLD_FAIL_PY = "=========================== short test summary info ============================\nFAILED tests/test_legacy.py::test_old_format - assert None\n1 failed, 11 passed in 0.40s\n"
NEW_FAIL_PY = OLD_FAIL_PY.replace("1 failed, 11", "2 failed, 10").replace(
    "FAILED tests/test_legacy.py::test_old_format - assert None\n",
    "FAILED tests/test_legacy.py::test_old_format - assert None\nFAILED tests/test_parse.py::test_dates - assert 2 == 3\n")
PASS_RS = "running 4 tests\ntest parse::dates ... ok\ntest result: ok. 4 passed; 0 failed; 0 ignored\n"
FAIL_RS = "running 4 tests\ntest parse::dates ... FAILED\ntest result: FAILED. 3 passed; 1 failed; 0 ignored\n"
PASS_GO = "ok  \texample.test/parse\t0.012s\n"
FAIL_GO = "--- FAIL: TestDates (0.00s)\n    parse_test.go:12: got 2 want 3\nFAIL\nFAIL\texample.test/parse\t0.010s\n"
DONE = "Done: the parser now handles dates and the bug is fixed."

PKG_VITEST = {"package.json": json.dumps({"name": "demo-app", "scripts": {"test": "vitest run"}}),
              "src/parse.js": "export const parse = s => s\n"}
PY = {"pyproject.toml": "[project]\nname = \"demo\"\n", "src/parse.py": "def parse(s):\n    return s\n",
      "tests/test_parse.py": "def test_x():\n    assert True\n"}
MONO = {
    "package.json": json.dumps({"name": "demo-mono", "private": True, "workspaces": ["packages/*"],
                                "scripts": {"test": "turbo run test"}}),
    "turbo.json": "{}",
    "packages/web/package.json": json.dumps({"name": "web", "scripts": {"test": "vitest run"}}),
    "packages/web/src/app.js": "export default 1\n",
    "packages/api/package.json": json.dumps({"name": "api", "scripts": {"test": "vitest run"}}),
    "packages/api/src/server.js": "export default 2\n",
}

FIX = []


def fx(name, repo, t, decision, contains=None, message=None, env=None, payload=None):
    FIX.append((name, repo, t, decision, contains, message, env, payload))


def with_files(base, **more):
    d = dict(base)
    d.update(more)
    return d


# --- core behaviour -------------------------------------------------------
fx("edit_then_test_pass", PKG_VITEST, T().edit("src/parse.js").bash("npm test", PASS_JS).say(DONE), "pass")
fx("edit_no_test", PKG_VITEST, T().edit("src/parse.js").say(DONE), "block", "run `npm test`")
fx("test_before_edit", PKG_VITEST, T().bash("npm test", PASS_JS).edit("src/parse.js").say(DONE), "block", "run `npm test`")
fx("edit_test_fail", PKG_VITEST, T().edit("src/parse.js").bash("npm test", FAIL_JS, 1).say(DONE),
   "block", "failed after your last edit")
fx("fail_then_fix_then_pass", PKG_VITEST,
   T().edit("src/parse.js").bash("npm test", FAIL_JS, 1).edit("src/parse.js").bash("npm test", PASS_JS).say(DONE), "pass")
fx("pass_then_edit_again", PKG_VITEST,
   T().edit("src/parse.js").bash("npm test", PASS_JS).edit("src/parse.js").say(DONE), "block", "run `npm test`")
fx("exit_code_line_without_flag", PKG_VITEST,
   T().edit("src/parse.js").tool("Bash", {"command": "npm test"}, out="Exit code 1\n" + FAIL_JS).say(DONE), "block")
fx("second_stop_lets_go", PKG_VITEST, T().edit("src/parse.js").say(DONE), "pass", payload={"stop_hook_active": True})
fx("no_claim_no_block", PKG_VITEST, T().edit("src/parse.js").say("I changed the parser. Should I also update the docs?"), "pass")
fx("negated_claim", PKG_VITEST, T().edit("src/parse.js").say("This is not fixed yet, the date case still breaks."), "pass")
fx("spanish_claim", PKG_VITEST, T().edit("src/parse.js").say("Listo, ya quedó arreglado."), "block")
fx("japanese_claim", PKG_VITEST, T().edit("src/parse.js").say("修正しました。"), "block")
fx("chinese_claim", PKG_VITEST, T().edit("src/parse.js").say("已修复。"), "block")
fx("write_new_file_no_test", PKG_VITEST, T().write("src/new.js").say(DONE), "block")
fx("bash_sed_edit_no_test", PKG_VITEST, T().bash("sed -i 's/a/b/' src/parse.js").say(DONE), "block")
fx("bash_redirect_edit_no_test", PKG_VITEST, T().bash("echo 'export const x = 1' > src/x.js").say(DONE), "block")
fx("bash_stderr_redirect_not_edit", PKG_VITEST, T().bash("node src/parse.js 2>/dev/null").say(DONE), "pass")
fx("edit_outside_repo", PKG_VITEST, T().edit("/tmp/scratch/notes.py").say(DONE), "pass")
fx("docs_only_edit", PKG_VITEST, T().edit("README.md").edit("docs/guide.txt").edit("CHANGELOG").say(DONE), "pass")
fx("docs_and_code_edit", PKG_VITEST, T().edit("README.md").edit("src/parse.js").say(DONE), "block")
fx("no_test_command", {"src/main.js": "console.log(1)\n"}, T().edit("src/main.js").say(DONE), "pass",
   message="no test command found")
fx("npm_default_test_uses_build",
   {"package.json": json.dumps({"name": "x", "scripts": {"test": "echo \"Error: no test specified\" && exit 1",
                                                          "build": "tsc"}}), "src/a.ts": "export {}\n"},
   T().edit("src/a.ts").say(DONE), "block", "npm run build")
fx("npm_build_ran",
   {"package.json": json.dumps({"name": "x", "scripts": {"build": "tsc"}}), "src/a.ts": "export {}\n"},
   T().edit("src/a.ts").bash("npm run build", "done in 1.2s").say(DONE), "pass")
fx("final_message_from_payload", PKG_VITEST, T().edit("src/parse.js"), "block",
   payload={"last_assistant_message": DONE})
fx("final_message_missing", PKG_VITEST, T().edit("src/parse.js"), "pass", message="could not read the final message")

# --- lockfile runner in the block message ---------------------------------
fx("runner_pnpm", with_files(PKG_VITEST, **{"pnpm-lock.yaml": "lockfileVersion: 9\n"}),
   T().edit("src/parse.js").say(DONE), "block", "run `pnpm test`")
fx("runner_yarn", with_files(PKG_VITEST, **{"yarn.lock": "# yarn\n"}), T().edit("src/parse.js").say(DONE),
   "block", "run `yarn test`")
fx("runner_bun", with_files(PKG_VITEST, **{"bun.lock": "{}\n"}), T().edit("src/parse.js").say(DONE),
   "block", "run `bun test`")

# --- equivalent commands for a package.json test script -------------------
for i, cmd in enumerate(["npm t", "npm run test", "npm run-script test", "pnpm test", "pnpm run test", "yarn test",
                         "yarn run test", "bun run test", "npx vitest run", "pnpm exec vitest run", "vitest run",
                         "npm test -- --reporter=dot", "CI=1 npm test", "cd __ROOT__ && npm test",
                         "NODE_ENV=test timeout 300 npm test"]):
    fx("matcher_js_%02d" % i, PKG_VITEST, T().edit("src/parse.js").bash(cmd, PASS_JS).say(DONE), "pass")
fx("matcher_js_wrong_script", PKG_VITEST, T().edit("src/parse.js").bash("npm run lint", "ok").say(DONE), "block")

# --- pipes ----------------------------------------------------------------
fx("piped_fail_no_pipefail", PKG_VITEST, T().edit("src/parse.js").bash("npm test 2>&1 | tail -20", FAIL_JS).say(DONE),
   "block", "failed after your last edit")
fx("piped_pass", PKG_VITEST, T().edit("src/parse.js").bash("npm test 2>&1 | tail -5", PASS_JS).say(DONE), "pass")
fx("piped_fail_pipefail", PKG_VITEST,
   T().edit("src/parse.js").bash("set -o pipefail; npm test | tail -5", FAIL_JS, 1).say(DONE), "block")
fx("masked_or_true", PKG_VITEST, T().edit("src/parse.js").bash("npm test || true", FAIL_JS).say(DONE), "block")
fx("piped_pytest_fail", PY, T().edit("src/parse.py").bash("pytest -q | tail -3", FAIL_PY).say(DONE), "block")
fx("piped_cargo_fail", {"Cargo.toml": "[package]\nname=\"demo\"\n", "src/lib.rs": "\n"},
   T().edit("src/lib.rs").bash("cargo test 2>&1 | tail", FAIL_RS).say(DONE), "block")

# --- monorepo runners -----------------------------------------------------
for i, (cmd, cwd) in enumerate([
        ("turbo run test", R), ("turbo run test --filter=web", R), ("npx turbo run test --filter web", R),
        ("nx test web", R), ("nx affected -t test", R), ("nx run-many -t test", R), ("pnpm -r test", R),
        ("pnpm --filter web test", R), ("npm -w web test", R), ("npm --workspace web test", R),
        ("npm test --workspaces", R), ("yarn workspace web test", R), ("yarn workspaces foreach run test", R),
        ("cd packages/web && npm test", R), ("pnpm test", R + "/packages/web"), ("npm test", R)]):
    fx("monorepo_%02d" % i, MONO, T().edit("packages/web/src/app.js").bash(cmd, PASS_JS, cwd=cwd).say(DONE), "pass")
fx("monorepo_wrong_filter", MONO, T().edit("packages/web/src/app.js").bash("pnpm --filter api test", PASS_JS).say(DONE),
   "block")
fx("monorepo_wrong_cd", MONO, T().edit("packages/web/src/app.js").bash("cd packages/api && npm test", PASS_JS).say(DONE),
   "block")
fx("monorepo_two_packages_one_tested", MONO,
   T().edit("packages/web/src/app.js").edit("packages/api/src/server.js").bash("pnpm --filter web test", PASS_JS).say(DONE),
   "block")
fx("monorepo_two_packages_both_tested", MONO,
   T().edit("packages/web/src/app.js").edit("packages/api/src/server.js")
   .bash("pnpm --filter web test", PASS_JS).bash("pnpm --filter api test", PASS_JS).say(DONE), "pass")

# --- pytest / cargo / go / others -----------------------------------------
for i, cmd in enumerate(["pytest", "python -m pytest", "python3 -m pytest -q", "uv run pytest", "poetry run pytest",
                         ".venv/bin/pytest -x"]):
    fx("pytest_%02d" % i, PY, T().edit("src/parse.py").bash(cmd, PASS_PY).say(DONE), "pass")
fx("pytest_scoped_note", PY, T().edit("src/parse.py").bash("pytest tests/test_parse.py -k dates", PASS_PY).say(DONE),
   "pass", message="scoped run")
fx("pytest_fail", PY, T().edit("src/parse.py").bash("pytest", FAIL_PY, 1).say(DONE), "block", "FAILED tests/test_parse.py")
fx("pytest_tests_dir_only", {"tests/test_a.py": "def test_a():\n    assert 1\n", "app.py": "x=1\n"},
   T().edit("app.py").say(DONE), "block", "run `pytest`")
CARGO = {"Cargo.toml": "[package]\nname=\"demo\"\n", "src/lib.rs": "\n"}
fx("cargo_pass", CARGO, T().edit("src/lib.rs").bash("cargo test --all", PASS_RS).say(DONE), "pass")
fx("cargo_fail", CARGO, T().edit("src/lib.rs").bash("cargo test", FAIL_RS, 101).say(DONE), "block")
fx("cargo_missing", CARGO, T().edit("src/lib.rs").bash("cargo build", "Finished").say(DONE), "block", "run `cargo test`")
GO = {"go.mod": "module example.test/parse\n", "parse.go": "package parse\n"}
fx("go_pass", GO, T().edit("parse.go").bash("go test ./...", PASS_GO).say(DONE), "pass")
fx("go_pass_one_pkg", GO, T().edit("parse.go").bash("go test ./parse/ -run TestDates", PASS_GO).say(DONE), "pass")
fx("go_fail", GO, T().edit("parse.go").bash("go test ./...", FAIL_GO, 1).say(DONE), "block")
fx("go_missing", GO, T().edit("parse.go").say(DONE), "block", "run `go test ./...`")
fx("make_test", {"Makefile": "test:\n\techo ok\n", "main.c": "int main(){}\n"},
   T().edit("main.c").bash("make test", "ok").say(DONE), "pass")
fx("make_missing", {"Makefile": "test:\n\techo ok\n", "main.c": "int main(){}\n"}, T().edit("main.c").say(DONE),
   "block", "run `make test`")
fx("just_test", {"justfile": "test:\n  echo ok\n", "main.sh": "echo\n"}, T().edit("main.sh").bash("just test", "ok").say(DONE), "pass")
fx("deno_test", {"deno.json": "{\"tasks\": {\"test\": \"deno test\"}}", "mod.ts": "\n"},
   T().edit("mod.ts").bash("deno task test", "ok | 3 passed | 0 failed").say(DONE), "pass")
fx("mix_test", {"mix.exs": "defmodule X do end\n", "lib/x.ex": "\n"}, T().edit("lib/x.ex").say(DONE), "block", "run `mix test`")
fx("rspec_test", {"Gemfile": "gem 'rspec'\n", "lib/x.rb": "\n"},
   T().edit("lib/x.rb").bash("bundle exec rspec", "10 examples, 0 failures").say(DONE), "pass")

# --- custom verify + off switches ------------------------------------------
CUSTOM = with_files(PKG_VITEST, **{"AGENTS.md": "# Agents\n\nverify: `./scripts/check.sh`\n"})
fx("agents_verify_missing", CUSTOM, T().edit("src/parse.js").bash("npm test", PASS_JS).say(DONE), "block",
   "run `./scripts/check.sh`")
fx("agents_verify_ran", CUSTOM, T().edit("src/parse.js").bash("./scripts/check.sh --fast", "all good").say(DONE), "pass")
fx("dotfile_verify_ran", with_files(PKG_VITEST, **{".done-check": "verify: make ci\n"}),
   T().edit("src/parse.js").bash("make ci", "ok").say(DONE), "pass")
fx("dotfile_off", with_files(PKG_VITEST, **{".done-check": "off\n"}), T().edit("src/parse.js").say(DONE), "pass")
fx("agents_verify_off", with_files(PKG_VITEST, **{"AGENTS.md": "- verify: off\n"}), T().edit("src/parse.js").say(DONE), "pass")
fx("env_off", PKG_VITEST, T().edit("src/parse.js").say(DONE), "pass", env={"DONE_CHECK": "off"})
fx("plugin_option_off", PKG_VITEST, T().edit("src/parse.js").say(DONE), "pass", env={"CLAUDE_PLUGIN_OPTION_ENABLED": "false"})

# --- baseline of old failures ----------------------------------------------
fx("baseline_old_failure_ignored", PY,
   T().bash("pytest", OLD_FAIL_PY, 1).edit("src/parse.py").bash("pytest", OLD_FAIL_PY, 1).say(DONE),
   "pass", message="already there before the edit")
fx("baseline_warn_blocks", PY,
   T().bash("pytest", OLD_FAIL_PY, 1).edit("src/parse.py").bash("pytest", OLD_FAIL_PY, 1).say(DONE),
   "block", "failed before your edit", env={"CLAUDE_PLUGIN_OPTION_BASELINE": "warn"})
fx("baseline_new_failure_blocks", PY,
   T().bash("pytest", OLD_FAIL_PY, 1).edit("src/parse.py").bash("pytest", NEW_FAIL_PY, 1).say(DONE),
   "block", "failed after your last edit")
fx("baseline_dotfile_warn", with_files(PY, **{".done-check": "baseline: warn\n"}),
   T().bash("pytest", OLD_FAIL_PY, 1).edit("src/parse.py").bash("pytest", OLD_FAIL_PY, 1).say(DONE),
   "block", "failed before your edit")


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for name, repo, t, decision, contains, message, env, payload in FIX:
        d = os.path.join(OUT, name)
        for rel, body in repo.items():
            p = os.path.join(d, "repo", rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(body)
        with open(os.path.join(d, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(t.dump())
        exp = {"decision": decision}
        if contains:
            exp["reason_contains"] = contains
        if message:
            exp["message_contains"] = message
        if env:
            exp["env"] = env
        if payload:
            exp["payload"] = payload
        with open(os.path.join(d, "expect.json"), "w", encoding="utf-8") as f:
            json.dump(exp, f, indent=1, ensure_ascii=False)
            f.write("\n")
    print("wrote %d fixtures to %s" % (len(FIX), os.path.relpath(OUT)))


if __name__ == "__main__":
    main()
