# HOP — Harness Optimization Profile (`mlpal/hop-v1`)

Status: v1.1. This document is the normative reference for the artifact; the reference
implementation is the loader in the MLPal Harness engine (`@mlpal/harness`,
`profile/schema` + `profile/load`), consumed by yodex ≥ 0.9.

**v1.1 is additive.** The spec id stays `mlpal/hop-v1` — a v1.0 artifact is a valid v1.1
artifact unchanged. v1.1 adds three optional top-level blocks (`model` §8, `requires` §9,
`safety` §10), an event-driven `tuning.triggers` array beside `cadence` (§6.2), a
categorical form for `tunable` ranges (`numeric | enum-set`, §6), and an optional versioned
directory layout (§2). Absent, every one of these leaves v1.0 behavior exactly as it was; a
v1.1 loader still refuses unknown top-level keys. Nothing here is a breaking change.

## 1. What a HOP is

A **HOP (Harness Optimization Profile)** is a declarative, versioned artifact that
configures an agent harness's *loop*, not just its edges:

- **capabilities** — the toolset, prompt slots
- **policies** — verification, permissions, routing, budgets
- **evals** — the definition of success for the profile's domain
- **telemetry** — the outcome facts every run stamps

A plugin adds capability at the edges of the loop (tools, instructions, hooks). A HOP
tunes the loop itself, and because it is declarative, versioned, and scored by its own
eval contract, it is the **unit of optimization**: a tuner can move any field declared
`tunable`, within its declared range, and measure the result — and may never touch a
field declared `locked`.

Throughout this spec the generic noun "profile" means a HOP. (The generic phrase
"harness profile" has narrower prior use — LangChain Deep Agents' `HarnessProfile` is
a per-model compatibility override layer. This spec's contribution is the integration:
loop policy + eval contract + telemetry contract + a declared optimization surface in
one artifact.)

## 2. Artifact form

A HOP is a **directory** containing `hop.yaml` plus any files it references:

```
my-profile/
  hop.yaml
  prompts/
    system.md
  evals/
    smoke/            # task dirs for declared eval suites
```

The directory is the unit of distribution (copy, git, tar). Profile identity lives in
`hop.yaml`, never in package-manager metadata. **Trust derives from where a profile
was discovered** (builtin < user dir < project dir < explicit path), never from fields
in the file.

**Discovery layout (v1.1).** A named HOP resolves under `hops/<name>/` in the project
(`.yodex/hops/`) then the user (`~/.yodex/hops/`) root. Two layouts are accepted:

```
hops/infra/hop.yaml            # flat: a single living version
hops/infra/1.2.0/hop.yaml      # versioned: one dir per pinned version
hops/infra/1.1.0/hop.yaml
```

A bare reference (`--hop infra`) resolves the flat file if present, else the highest
semver under the versioned layout; a pinned reference (`--hop infra@1.1.0`) selects that
version directory. The flat and versioned layouts are mutually exclusive within one
`hops/<name>/` — a loader that finds both errors rather than guess. Until a hosted
registry exists, this filesystem layout **is** the registry.

## 3. hop.yaml

```yaml
spec: mlpal/hop-v1        # REQUIRED. Unversioned artifacts are refused.
name: strict-eng              # lowercase kebab-case; names dirs + telemetry dims
version: 0.1.0                # the profile's own semver
description: Coding with a hard verification gate.
extends: coding               # builtin name or relative dir path; single inheritance

prompts:
  system: file:prompts/system.md   # inline string or file:<relpath>
  verifierAgent: file:prompts/verifier.md
  summarizer: "..."                # side-call prompt slots
  condenser: "..."

verification:
  observe: builtin:coding     # verification-command vocabulary: builtin:coding|builtin:none
  selfCheck: { enabled: true, minEdits: 3 }
  antiChurn: { enabled: true, threshold: 6 }
  agent:                      # adversarial verifier at the finish gate
    enabled: true
    tier: mid                 # cheap|mid|frontier|max
    riskGateMinChangedLines: 6
    failMode: open            # open | closed  (closed: no explicit PASS => no finish)

catalog: { profile: coding }  # gateway catalog curation slice

routing:
  subagents: catalog          # catalog | inherit | budget:<economy|balanced|quality>
  classifyStart: false
  escalation: { ladder: off, patience: 2 }   # ladder: catalog | off

model:                        # v1.1 — the loop's model policy (§8). Optional; absent => host default.
  main: frontier              # tier alias {cheap|mid|frontier|max} or a pinned id (claude-opus-5)
  subagents: { readOnly: cheap, verify: mid }
  allowInvokeAny: true        # the loop may call any catalog model via the gateway

permissions:
  defaultMode: autopilot      # applied only when the user set no mode themselves
  allow: []                   # rule syntax: Tool or Tool(pattern), * wildcard
  deny: []                    # concatenates down the chain — a one-way ratchet

safety:                       # v1.1 — the apply-safety envelope (§10). LOCKED whenever present.
  toolClasses:                # per-action class (drives the applies/infra capability tags)
    readOnly: [...]
    mutative: [...]
    destructive: [...]
  preApply: { requirePlanArtifact: true, hash: [plan, identity, backend, toolVersion, lockfile, policyResults] }
  blastRadius: { maxResources: 25, accounts: [self], regions: [us-east-2], requireTag: HopManaged=true }
  approval: { destructive: always, outOfScope: always, costCeilingUsdMonth: 200 }
  identities: { read: hop-read, write: hop-change-<workload>, neverSelfGrant: true }

tools:
  include: []                 # allowlist over registered tools; [] = all

requires:                     # v1.1 — external prerequisites checked at preflight (§9). Optional.
  binaries:
    - { name: aws, detect: "aws --version", setup: "https://docs.aws.amazon.com/cli/" }
  mcp:
    - { name: aws-mcp }

budgets:
  maxTurns: 200

telemetry:
  taskType: coding            # dimension stamped on run-outcome feedback

evals:
  - name: smoke
    tasks: evals/smoke        # dir of task dirs (repo/ + prompt.txt + hidden checks)
    scorer: "python -m pytest -q"
    runs: 2
    passBar: 1.0
    role: probe               # golden | frontier | probe (see §6); unset = informational
  - name: coding-golden
    tasks: evals/golden
    scorer: "python -m pytest -q"
    runs: 3
    passBar: 1.0
    role: golden              # mandatory-pass, gates by default
  - name: token-cost
    tasks: evals/frontier
    scorer: "python score_tokens.py"   # scorer computes the tuned number
    runs: 3
    passBar: 0
    role: frontier

tuning:                       # how + when this HOP is tuned; the promotion gate (§6.2)
  cadence: daily              # daily | weekly | monthly | on-incident | per-<N>-runs
  triggers: [on-model-release, on-incident]   # v1.1 — event triggers beside the scheduled cadence
  minRunsSinceLast: 200       # statistical-power floor before a proposal
  canaryFraction: 0.1
  canaryMinRuns: 50
  promote: human              # human | auto (auto needs a mandatory-pass golden gate)
  frontierMetric: token-cost  # an eval with role: frontier
  promotionMargin: "-5% at p<.05"
  goldenSuite: coding-golden  # an eval with role: golden

locked: []                    # dot paths no child, user setting, or tuner may touch
tunable:                      # the declared optimization surface
  - path: verification.selfCheck.minEdits
    range: [1, 10]            # numeric range [min, max]
  - path: model.main
    range: [frontier, max]    # v1.1 — categorical range (enum-set), not numeric
```

Unknown top-level keys are a **hard error**, not a silent ignore.

## 4. Composition and precedence

A profile composes over its `extends` parent **per leaf** (deep merge): a present leaf
in the child overrides that leaf only; absent leaves inherit. There is deliberately no
whole-block replacement — restating a block to change one field is the failure mode
this spec exists to avoid.

Special rules:

- `permissions.deny` **concatenates**; a child (or user) can add deny rules but never
  remove an ancestor's. `permissions.allow` also concatenates but is lock-checkable,
  because added allows can loosen policy.
- `tools.include` and each `tunable` entry replace **whole-value per name/path** —
  merging halves of two lists produces artifacts nobody wrote.
- `locked` accumulates down the chain.

Runtime precedence, lowest to highest:

```
engine defaults < profile chain (root → leaf) < project settings < user settings < env < flags
```

The user outranks the artifact they installed — **except** `locked` paths, where an
explicit override is a **hard error naming the locking profile**. Silently ignoring an
override would make the lock a lie; silently obeying it would make the profile one.
Schema defaults in user settings never count as explicit user intent.

## 5. Verification is a seam, not a feature

Every profile carries a `verification` block; the harness routes all of its completion
gates through it:

1. **observe** — which commands count as "the agent verified its work"
   (`builtin:none` for domains where command exit codes are not evidence).
2. **selfCheck** — one nudge at the finish if real edits were made but nothing was
   verified.
3. **antiChurn** — one mid-loop nudge when a single file is edited `threshold` times
   with no verification between.
4. **agent** — an independent verifier agent at the finish gate. `failMode: open`
   permits PARTIAL/unverifiable outcomes (prevents runaway loops); `failMode: closed`
   blocks anything but an explicit PASS — the setting for domains where an unverified
   result must not be delivered. Fail-closed profiles never skip verification via the
   risk gate.

Harness requirement: loop heuristics MUST key off tool **capability tags** (edits /
executes), never tool names, so a profile with a restricted or renamed toolset keeps
its verification signals.

## 6. Evals and telemetry

`evals` declares how this profile is scored: suites of task directories with hidden
checks, a scorer command, run count, and a pass bar. `telemetry.taskType` names the
dimension stamped on every run outcome (escalations, verifier verdicts, token usage).
Together they are what make a profile *scoreable* — a profile without them is just a
config bundle, and the tuning loop has nothing to hold on to.

`tunable` declares the optimization surface explicitly: path + range. A tuner may move
only declared paths, only within range, and never a `locked` path. Published eval
suites are referenced immutably (a digest pins the task set) so a tuned profile can't
grade itself against a drifted rubric.

A **range is `numeric | enum-set`** (v1.1). A numeric range `[min, max]` bounds a
continuous knob (`[1, 10]`); an enum-set range `[a, b, c]` enumerates the allowed values
of a categorical knob — `model.main: [frontier, max]` lets the tuner route between tiers,
the one thing a numeric range could not express. A move is in-range if the target is
within the numeric bounds, or a member of the enum set. (Absent this, a model/tier knob
had no declarable range at all — the gap that made tier routing an unenactable proposal.)

### 6.1 Eval roles and the deterministic-gates-only rule

Each eval suite may declare a `role`, and a `gates` boolean:

- **golden** — mandatory-pass, frozen correctness invariants that may never regress. A
  candidate failing any golden is rejected outright, no tradeoff math. `gates: true` by
  default.
- **frontier** — the scored metric being tuned (its scorer *computes the number*:
  median tokens, $/task, resolve rate, wall time). Promotion requires the preregistered
  margin on it. `gates: false` (it is scored, not a pass/fail gate).
- **probe** — cheap deterministic smoke that kills obviously broken candidates before
  expensive evals spend money. `gates: true` by default.

The hard rule: **anything that gates promotion must be deterministic and re-runnable**.
An LLM-judged suite MUST set `gates: false` — it informs, it never gates. The loader
defaults `gates` by role; an author overrides it explicitly, and the tuner honors it.

### 6.2 `tuning` — how and when a HOP is optimized

`tuning` is the control-plane complement to `tunable` (what may move) and `locked`
(what may never): it declares the cadence and the promotion gate. Fields:

| Field | Meaning |
|---|---|
| `cadence` | `daily` \| `weekly` \| `monthly` \| `on-incident` \| `per-<N>-runs`. A property of the HOP, derived by the author from telemetry volume, environment drift rate, blast radius, and eval cost — high-traffic read-only HOPs tune daily; payment/infra HOPs tune slowly. |
| `triggers` | v1.1, optional. Event-driven re-tune triggers **beside** the scheduled `cadence`: `on-model-release` (a new catalog model is a mandatory EVALUATION, not a blind migration), `on-api-change`, `on-incident`. `cadence` is the clock; `triggers` are the interrupts. Both are subject to the same evidence gate below — a trigger fires a cycle, it does not fire a promotion. |
| `minRunsSinceLast` | statistical-power floor: a proposal needs at least this many new runs. |
| `canaryFraction` / `canaryMinRuns` | canary rollout size before promote/rollback is decided. |
| `promote` | `human` (a person merges the promotion) or `auto` (green evals promote). |
| `frontierMetric` | names an eval suite with `role: frontier`. |
| `promotionMargin` | the preregistered win bar, e.g. `"-5% at p<.05"`. |
| `goldenSuite` | names an eval suite with `role: golden`. |

Load-time enforcement: `frontierMetric` must resolve to a `role: frontier` suite and
`goldenSuite` to a `role: golden` suite; `promote: auto` is refused unless the golden
suite actually gates (`gates: true`) — you cannot auto-promote without a mandatory-pass
gate. A tuning block is all-or-nothing: a partial block is a loud error. `tuning` is
lock-checkable — a parent that sets `locked: [tuning.promote]` forces `human` on every
child (a blast-radius ratchet). The deeper blast-radius gate on `promote: auto` (an
apply-capable HOP may not self-promote) is enforced by the tuner, which resolves tool
capability tags the loader does not have.

### 6.3 Telemetry contract (D11.2)

Every run emits one **content-free** run-outcome event — the Capture stage of the
optimizer. Content-free by construction: the payload is an explicit allowlist of
outcome facts, never transcript text, so fleet aggregation has nothing to leak. The
payload carries: `hop {name, version}`, `model`, `tier`, `task_type`, `run_result`
(`success` \| `error` \| `max_turns` \| `cancelled`), `failure_class`, a per-mechanism
`checks` map (`self_check` / `anti_churn` / `observe {ran, passed}` / `agent {verdict}`),
`tokens {input, output, cache_read_input, cache_creation_input}`, `wall_ms`, and `turns`.

`run_result` is loop **completion**, not task correctness: `success` means the run reached
its finish gate without error/stall/abort — a wrong-but-complete answer is still `success`.
Whether the work is correct is a graded, out-of-band signal this content-free event
deliberately omits; a consumer joins it from an external grader and must never read `success`
as "resolved". A tuner's frontier metric is scored on the eval contract (§6.2), never inferred
from `run_result`.

`failure_class` is the failure-taxonomy label (`failure_class_vocab@v1`): `empty_patch`,
`step_budget_stall`, `test_timeout`, `tool_error`, `gateway_error`, `verifier_reject`,
`user_cancelled`, `other`. It is **null iff `run_result` is `success`**. An emitter that
cannot classify a failure emits `other` — never the nearest bucket, because unclassified
volume is itself a signal. `contract: "d11.2"` marks the version; consumers accept prior
versions under their own stamp rather than coercing.

## 7. Host plane (what a profile can never reach)

The harness's catastrophic-action denials and protected-write rules, credential and
gateway configuration, the session store, and spec-version handling are host-owned. A
profile configures policy *inputs*; it cannot replace the permission engine, the
sandbox, or the loop implementation itself.

## 8. Model policy (v1.1)

The optional `model` block declares the loop's model, so model choice is a HOP field a
tuner can move — not a runtime accident. Before v1.1 the served model was chosen by the
runner/settings/catalog and no HOP field named it, so "route this class to a different
tier" was a proposal with no knob to enact. `model` closes that.

- `main` — the main loop's model: a tier alias (`cheap|mid|frontier|max`, resolved through
  the catalog) or a pinned id (`claude-opus-5`). The premium, domain-appropriate model the
  loop runs on.
- `subagents` — per-role subagent model policy (`{readOnly, verify}`, tier or id): a cheap
  tier for read-only inventory/triage, a stronger one for verification. Composes with
  `routing.subagents` (which selects the *strategy*); `model.subagents` names the *tiers*
  that strategy draws from. A cheap subagent never authorizes or executes a mutation.
- `allowInvokeAny` — guidance (default true): the loop may invoke any catalog model via the
  gateway on demand. A capability statement, not a restriction; the user's `/model` control
  and session overrides always outrank the artifact.

`model.main` and `model.subagents.*` are declarable `tunable` with an **enum-set** range
(§6), so a tuner may route between tiers within the declared set — eval-gated like any other
move (a model change must clear the golden gate and the frontier margin, never a blind swap).
The `on-model-release` trigger (§6.2) fires exactly this: a new catalog model is a mandatory
evaluation of `model.main` against it, not an automatic migration.

## 9. Requirements and preflight (v1.1)

A HOP that needs external tools declares them; the host checks them before the run instead
of failing mid-task. `tools.include` gates *registered* tools; `requires` declares the
*external prerequisites* those tools depend on.

```yaml
requires:
  binaries:
    - { name: aws, detect: "aws --version", setup: "<url or command>" }
    - { name: terraform, detect: "terraform version" }
  mcp:
    - { name: aws-mcp }          # an MCP server the HOP expects connected
```

The **preflight contract**: before the first run under a HOP, the host runs each `detect`
command, connects each declared `mcp` server, and **reports every gap loudly** — a HOP whose
requirements are unmet says so and offers `setup`, it never silently degrades into a HOP that
cannot do its job. A HOP may order its detection (e.g. cloud A then B then C) so the setup
guidance fits what is present. Preflight is a host capability; the HOP only *declares* the
requirements, and a domain's canonical detector should be referenced, not re-derived per HOP.

## 10. Safety envelope (v1.1)

A HOP that performs mutating or destructive real-world actions (infra, deploys) carries a
`safety` block: the declared, versioned envelope inside which the loop is autonomous, and the
edge at which it must stop and ask. It is **LOCKED whenever present** — neither a child, a
user setting, nor the tuner may loosen it — and it configures *policy inputs*; the host-owned
catastrophic denials (§7) stay host-owned and cannot be widened by it.

```yaml
safety:
  toolClasses: { readOnly: [...], mutative: [...], destructive: [...] }
  preApply: { requirePlanArtifact: true, hash: [plan, identity, backend, toolVersion, lockfile, policyResults] }
  blastRadius: { maxResources, accounts, regions, requireTag }
  approval: { destructive: always, outOfScope: always, costCeilingUsdMonth }
  identities: { read, write, neverSelfGrant: true }
```

- **toolClasses** classify every action read-only / mutative / destructive. The harness
  carries these as **capability tags** (`applies`, `infra`) on the tools, so the gate keys
  off the action class, not a tool name — a renamed or wrapped CLI keeps its class.
- **preApply** — an apply is admitted only if it matches a reviewed **plan artifact** whose
  hash covers the plan + identity + backend + tool version + lockfile + policy results. The
  loop applies the hashed plan, never an ad-hoc command; enforcing this is stateful (the gate
  consults the run's own dry-run record), not a tag check.
- **blastRadius** — a hard ceiling: resource count, account/region allowlist, a required
  ownership tag. A plan outside it is out-of-envelope.
- **approval** — the edge. A plan in the DESTRUCTIVE class, outside the allowlist, or over the
  cost/resource ceiling stops and asks. The ask **binds to the exact normalized command +
  targets + expiry**, never "approve the deploy". In a headless/scheduled run the ask resolves
  to a structured `needs_approval` terminal outcome (with the pending action captured out of
  band), never a hang.
- **identities** — the read identity and the write identity are distinct; the loop never
  self-grants the writer role and never holds writer credentials in context.

Everything inside the envelope is free (default mode `cruise`); only the edge asks. The
envelope is a locked artifact field precisely so the boundary is auditable and evolves only
through the eval-gated tuning loop, never a per-step human judgment call.

## 11. Conformance

An implementation conforms if it: refuses artifacts without `spec:`; rejects unknown
top-level keys loudly; composes per §4 including lock enforcement at both compose time
and settings-application time; applies the toolset allowlist to **every** run path the
session can spawn (sub-agents, peer agents, workflow agents) so a restricted profile
cannot launder capability through a child; stamps `telemetry.taskType` on run outcomes;
validates `tuning` references against declared eval roles and refuses `promote: auto`
without a gating golden suite (§6.2); and emits the content-free D11.2 run-outcome
envelope (§6.3) with `failure_class` null iff success.

**v1.1 additions.** A conforming v1.1 loader additionally: accepts every v1.0 artifact
unchanged (the new blocks are optional; their absence is v1.0 behavior); treats `model`,
`requires`, and `safety` as optional top-level blocks; accepts a `tunable` range in either
form (`numeric [min,max]` or `enum-set [a,b,…]`) and bounds a move accordingly; **locks the
`safety` block whenever present** (no child/user/tuner override); accepts `tuning.triggers`
as an event-trigger array beside `cadence`; resolves both the flat and versioned discovery
layouts (§2), erroring if a single `hops/<name>/` holds both. Preflight (§9) and the safety
evaluator (§10) are host capabilities the loader enables, not parse-time behavior.
