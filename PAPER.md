# HOP — Harness Optimization Profiles: the agent loop as a versioned, evaluated, tunable artifact

MLPal · 2026-08 · contact@mlpal.ai

## Abstract

Coding-agent harnesses hide their most consequential decisions — when to verify, which
model runs which subtask, what a session may touch, when to stop — in code. Config
surfaces exist, but they either configure a harness without defining its objective, or
(in the research literature) optimize an agent without standardizing the artifact being
optimized. We describe **harness profiles** (`mlpal/hop-v1`): a declarative,
versioned artifact carrying a harness's loop policy (verification, permissions,
routing, budgets, prompts, toolset) together with an **eval contract** defining success
in its domain, a **telemetry contract** every run stamps, and an explicitly declared
**optimization surface** (`tunable` ranges, `locked` fields). We split yodex, our
coding agent, into a bare engine plus a coding profile — byte-identical to the
pre-split harness by golden test — and demonstrate generality with a reviewer profile
that changes the loop, not the prompt: a read-only toolset enforced across all spawned
sub-agents, cheap-model scanning, and a fail-closed independent verifier that blocks
delivery of any claim it cannot evidence-check. A paired benchmark against the
pre-split release shows no quality or efficiency regression.

## 1. The problem

Every serious harness embeds domain policy in code. In yodex 0.8.0 we counted the ways:
a regex deciding which shell commands count as "verification"; nudge strings for
self-check and anti-churn spirals; a summarizer prompt that says "you compress a coding
session"; a verifier prompt that assumes `git diff` exists; a risk gate readable only
through an environment variable. None of it was visible, diffable, or measurable — and
none of it transferred to a second domain.

The plugin answer (most recently DeepSeek Harness, where everything is a plugin) makes
*capabilities* composable but leaves loop policy either hardcoded or unowned: dsh ships
no config surface for model routing (its model binding is a flat `{provider, model}`
singleton), none for verification or critic steps, and no evals package at all. Its
own benchmark file is three lines. Configuring the parts is not the same as owning the
tune of the whole.

The research answer (AHE — Agentic Harness Engineering; "A Self-Improving Coding
Agent," which lifted a SWE-bench Verified subset from 17% to 53% by editing its own
harness) proves the harness is the highest-leverage optimization target. But these
systems mutate harness *code*, so what they learn is neither portable, auditable, nor
safely boundable.

The gap is an artifact: something declarative enough to diff and version, complete
enough to carry the loop's policy, and honest enough to carry its own definition of
success — so optimization becomes a typed search over declared ranges rather than
open-ended self-modification.

## 2. The artifact

A profile is a directory with a `hop.yaml` (full schema in the spec):

- **capabilities** — toolset allowlist, prompt slots (system, verifier, summarizer,
  condenser)
- **policies** — verification (observation vocabulary, self-check, anti-churn,
  independent verifier with `failMode: open|closed`), permissions (default mode +
  rules), routing (sub-agent difficulty gating, escalation), budgets
- **evals** — task suites with hidden checks, a scorer, and a pass bar
- **telemetry** — the task-type dimension stamped on every run outcome
- **locked / tunable** — the governance and optimization surface: locked paths are
  enforced against child profiles, user settings, and the tuner (a violation is a hard
  error naming the locking profile); tunable paths declare ranges a tuner may search

Definition we find useful: *a plugin adds capability at the edges of the loop; a
profile tunes the loop itself.* What makes the profile more than a config bundle is the
pairing with evals and telemetry — a profile is scoreable, so it can get better.

Composition is single-inheritance with per-leaf deep merge (no whole-block
replacement — dsh documents whole-row config replacement as its own top limitation, and
we take the hint), a deny-list concat ratchet (a child can tighten, never loosen), and
user-over-profile precedence everywhere except locked paths. The artifact declares
`spec: mlpal/hop-v1` on pain of refusal; versioned from day one because the
migration path you don't design is the one you need.

## 3. The verification seam

Verification is the load-bearing policy, so it is a seam, not a feature. All four of
the harness's completion mechanisms read one policy block: the observation vocabulary
(which commands count as having verified; `builtin:none` for domains where exit codes
aren't evidence), the finish-time self-check, the mid-loop anti-churn breaker, and the
independent adversarial verifier with an explicit failure semantic — `open` (an
unverifiable result may ship, with the caveat said aloud) or `closed` (no explicit PASS,
no delivery; the gate never risk-skips).

One implementation detail matters beyond our codebase: loop heuristics must key off
tool **capability tags** (`edits`, `executes`), never tool names. Name matching
silently disabled self-check and anti-churn for any profile with a renamed or
restricted toolset — the kind of bug that never fires in the default configuration and
always fires in the second profile. Likewise the toolset allowlist must bind every run
path the session can spawn — sub-agents, peer agents, workflow agents — or a
restricted profile can launder capability through a child.

## 4. Two profiles, one engine

**coding** is yodex's default, extracted verbatim: golden tests pin every extracted
string and threshold byte-identical to the 0.8.0 hardcoded originals, and a paired
benchmark (§6) checks the end-to-end claim.

**reviewer** is the generality proof, different in policy rather than prose:
`tools.include` omits Write/Edit entirely (and the capability-tag design means
self-check/anti-churn correctly self-disable rather than misfire); permissions default
to read-only mode and are **locked**; verification observes no commands, and the
independent verifier runs fail-closed with a review-audit protocol — open every cited
file:line, test each claimed failure scenario that can be cheaply tested, fail the
review if any finding is miscited, unreachable, or unevidenced. In live runs the
reviewer finds seeded defects with line-anchored evidence, cannot modify the repository
even through sub-agents, and cannot finish until its audit passes.

## 5. Related work

Declarative agent configuration is a crowded space; the integration is not. LangChain
Deep Agents' `HarnessProfile` (the closest name) is a per-model compatibility override
layer — prompts, tool inclusion, middleware — with no evals, budgets, verification, or
telemetry. OpenAI Codex CLI has the broadest incumbent loop-knob coverage (per-role
models and reasoning effort, a reviewer model, compaction and memory configuration,
experimental rollout token budgets, OTEL export) but no semantic routing rules,
mandatory verifier semantics, attached evals, or a declared search space. Claude Code
layers permissions, hooks, subagent frontmatter, and plugins across several files with
no single versioned artifact. DeepSeek Harness composes plugin runtimes from
profile/bundle patch layers with excellent ergonomics (provenance-annotated config
dumps computed through the boot path — an idea we adopt) but ships no routing,
verification, or eval surface, no schema version, and no migration story. Roo/Cline
modes, OpenCode config, Aider's architect/editor split, and Goose recipes each carry
fragments. On the eval side, promptfoo/LangSmith/Braintrust bind tests to prompts or
datasets external to the runtime artifact. On the optimization side, DSPy/MIPROv2,
TextGrad, and commercial optimizers tune prompts; ADAS, AFlow, and GPTSwarm search
scaffolds as code; AHE and Self-Harness optimize the harness itself without a
standardized artifact. Azure's Agent Optimizer and Databricks Agent Bricks tune
multiple config surfaces as hosted products without a portable, version-controlled
profile.

Our claim is deliberately narrow: not the first declarative agent config, critic loop,
or agent optimizer — the first artifact we know of that binds loop policy, an eval
contract, a telemetry contract, and a typed optimization surface together, which is
what makes harness optimization auditable rather than open-ended.

## 6. No-regression benchmark

Splitting the shipping harness is only free if the split costs nothing. We ran the
paired comparison: published yodex 0.8.0 (pre-split) vs. the profile-ized build, same
pinned model (claude-opus-5), same four contamination-free tasks from our five-harness
panel (two easy: ledger ordering, slug normalization; two hard: a scheduler
race-condition fix, a rate limiter implemented from a spec), hidden test suites,
N=2 per cell, serial runs on one machine.

| task | build | correct | output tok (avg) | turns (avg) | wall s (avg) |
|---|---|---|---|---|---|
| easy: ledger | 0.8.0 | 2/2 | 3,298 | 9.0 | 48.1 |
| easy: ledger | profiles | 2/2 | 2,382 | 8.5 | 39.0 |
| easy: slug | 0.8.0 | 2/2 | 2,886 | 10.5 | 50.4 |
| easy: slug | profiles | 2/2 | 2,423 | 9.0 | 38.7 |
| hard: scheduler | 0.8.0 | 2/2 | 28,021 | 30.0 | 396.6 |
| hard: scheduler | profiles | 2/2 | 19,627 | 18.5 | 282.6 |
| hard: ratelimit | 0.8.0 | 2/2 | 13,051 | 9.5 | 162.7 |
| hard: ratelimit | profiles | 2/2 | 13,544 | 12.5 | 172.3 |
| **total** | **0.8.0** | **8/8** | **94,515** | 118 | — |
| **total** | **profiles** | **8/8** | **75,953** | 97 | — |

Both builds solved every task in every run. The profile-ized build's lower token
total (−20%) is directionally pleasant but driven largely by one expensive 0.8.0
scheduler run (33k tokens, 36 turns); at N=2 the honest claim is **parity** — the
split changed the artifact boundary, not the behavior — with same-harness
run-to-run spread of the same order as the between-build difference. The grading
harness was validated two-way before any run counted (the reference solution must
pass each hidden suite; the unmodified repo must fail it). Raw run logs, tasks,
hidden suites, and the runner ship with the spec repo.

## 7. What profiles are for (the loop that closes)

The artifact is step one of a ladder we are explicit about: (1) run-outcome telemetry
per profile version — shipped; (2) per-repo profile tuning: routines that run the
profile's eval suites and move `tunable` fields within their ranges, proposing a
version-bumped diff; (3) skill and memory induction feeding profile-owned prompt
slots; (4) fleet priors: aggregate outcome telemetry (never content) improving shipped
profile defaults. Locks and sealed eval references are what keep every rung auditable:
the tuner can prove it only touched what the artifact said it could, and scored
against a rubric it could not rewrite.

## 8. Limitations

v1 profiles are pure data; templated prompt slots (nudges, classifier) are only
definable in builtin profiles, and code-level extensions (custom verification-command
detectors) are named builtins, not loadable plugins — we hold the line at data until
concrete third-party uses exist. Eval running is local; hosted eval infrastructure and
the tuner itself are future work (rungs 2–4 above). The sandbox vocabulary is
reserved but not yet specified. Verifiable domains came first by design: a profile for
a domain with no cheap oracle (much of legal work) can carry policy and locks today
but cannot yet self-improve honestly, and we would rather say that than imply
otherwise.

## Availability

Spec and examples: github.com/mlpal-ai/hop. Reference implementation: yodex
(`npm install -g @mlpal/yodex`), `yodex hop list|show|lint`. Benchmark tasks,
hidden suites, and raw run logs: published with the spec repo.
