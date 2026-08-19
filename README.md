# Harness profiles (`mlpal/profile-v1`)

A harness profile is a declarative, versioned artifact that configures a coding-agent
harness's **loop** — verification policy, permissions, model routing, budgets, prompts,
toolset — plus the **eval contract** that defines success in its domain and the
**telemetry** every run stamps. Because the artifact is versioned, diffable, and
scored by its own evals, it is the unit of optimization: tuning moves declared
`tunable` fields within declared ranges and measures the result; `locked` fields are
enforced against children, user settings, and the tuner alike.

Plugins add capability at the edges of a loop. A profile tunes the loop itself.

- **[SPEC.md](SPEC.md)** — the normative v1 specification
- **[examples/](examples/)** — small real profiles (a fail-closed engineering profile,
  a hardened reviewer)
- **[PAPER.md](PAPER.md)** — design, related work, and the no-regression benchmark
- **[bench/](bench/)** — the benchmark: tasks, hidden suites, runner, raw logs

## Trying it

The reference implementation ships in [yodex](https://github.com/mlpal-ai/yodex):

```
npm install -g @mlpal/yodex
yodex profile list                 # builtins: coding (default), reviewer
yodex --profile reviewer           # same engine, different loop policy
yodex profile lint ./my-profile    # validate an artifact
yodex profile show                 # the composed active profile
```

A profile is a directory with a `profile.yaml`; put it in `.yodex/profiles/<name>`
(project) or `~/.yodex/profiles/<name>` (user) and select it with `--profile <name>`,
`YODEX_PROFILE`, or `"profile"` in settings.

The two builtins are deliberately policy-different, not prompt-different: `coding`
verifies by running the project's checks and fails open; `reviewer` is read-only
(enforced at the tool registry for the session *and every sub-agent it spawns*),
routes scanning to cheap models, and fail-closes — a review whose claims can't be
independently evidence-checked is not delivered.

## Status

v1. The spec covers the artifact, composition, lock semantics, the verification seam,
and the eval/telemetry contracts. Declared-but-minimal in v1: eval suite running is
local (`yodex profile eval`), and templated prompt slots (nudges, classifier) are
inheritable but only definable in builtin profiles. Both are called out inline in
SPEC.md.

Prior art note: LangChain Deep Agents uses "harness profile" for a per-model
compatibility override layer; DeepSeek Harness profiles compose plugin runtimes.
Neither carries loop policy with an eval and telemetry contract as one artifact —
that integration is what this spec specifies. Full comparison in [PAPER.md](PAPER.md).

## Contact

contact@mlpal.ai
