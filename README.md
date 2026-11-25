# done-check
Stops your Claude Code agent from saying "done" until your tests have passed after its last code change.

```
claude plugin marketplace add kilazi/done-check && claude plugin install done-check@kilazi
```

Restart Claude Code. If the agent edits code and says done without a passing test run, it is sent back once to run your tests; a second stop goes through.
Works with npm, pnpm, yarn, bun, pytest, cargo, go, make or your own command. Needs python3. Off: `export DONE_CHECK=off`.
Apache-2.0. Reusing it? Keep the NOTICE: credit kilazi/done-check.

More: https://kilazi.com/wiki/done-check/ · by kilazi
