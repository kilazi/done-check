# done-check
done-check: your agent's 'done' needs a passing test after its last edit.

## Use
```
claude plugin marketplace add kilazi/done-check; claude plugin install done-check@kilazi
```
Restart your session. When the agent edits code and then says done, fixed or works without a passing run of your tests after its last edit, it is sent back once to run them; the second stop goes through. Any runner counts: npm, pnpm, yarn, bun, turbo, nx, pytest, cargo, go, make, or your own `verify: <command>` in AGENTS.md. Piped runs (`npm test | tail`) are judged by their output, and tests that already failed before the edit do not block.

Enforced on Claude Code 2.1.291. macOS, Linux; Windows untested. Needs python3. Off: `claude plugin configure done-check`, `verify: off` in AGENTS.md, or `DONE_CHECK=off`. Update: `claude plugin marketplace update kilazi`. Tests: `python3 test/run.py`.

More: https://kilazi.com/wiki/done-check/ · by Max Kilazi (https://kilazi.com)
