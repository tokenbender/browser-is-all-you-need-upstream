# Targeted topic coverage audit

This opt-in CPU audit adds behavioral coverage for allergies, bank-account,
circular-buffer, clock, complex-numbers, dnd-character, grade-school, space-age,
sublist, yacht and perfect-numbers. The standalone CLI produces audit receipts;
`generalized_cpp_topic_grpo` consumes them for training rewards. The CLI does not
launch training. CHARM tasks are outside this package.

The existing generalized task resolver authenticates the manifest and protected
fixtures. Each specialist compiles a trusted reference before auditing a
candidate against independent expected results. Candidate sources are copied to
a temporary workspace. There are 64 behavioral groups and two separate
diagnostics. Reference and candidate behavioral groups run twice in fresh
processes. Inconsistent candidate outcomes on fixed inputs produce FAIL when the reference
is healthy. Process-launch errors and unhealthy references produce INVALID. Character generation uses fresh candidate randomness: a concrete rule
violation remains a failure even if its sample index differs across runs.
This is repeatability evidence, not proof over every input.

## Run

From the repository root, with GCC and repository Python dependencies:

~~~sh
PYTHONPATH=src python3 -B -m Reward_GRPO.topic_coverage validate \
  --output /tmp/topic-coverage-validation-NEW --compare-generalized --allow-local-execution

PYTHONPATH=src python3 -B -m Reward_GRPO.topic_coverage check \
  --task circular-buffer --candidate-dir /path/to/candidate \
  --output /tmp/buffer-audit-NEW --include-diagnostics --allow-local-execution

PYTHONPATH=src python3 -B -m Reward_GRPO.topic_coverage check \
  --task allergies --response-file /path/to/aider-response.txt \
  --output /tmp/allergies-audit-NEW --with-generalized --allow-local-execution
~~~

Use a new output directory each time. A candidate directory supplies the
registered .h and .cpp pair; a header-only solution may supply an empty .cpp.
The --response-file option uses existing Aider reconstruction; --reference
audits the registered reference without editing the starter.
The --with-generalized option stores the original generalized reward separately
in generalized.json, using a credential-free subprocess; it does not combine
scores. The baseline uses its own compiler/runner defaults, not the topic
--compiler override. Exit codes describe only the
extra audit: 0 pass, 1 candidate failure, 2 invalid/configuration error.
A topic PASS does not claim complete official-task correctness.

## Scope and reasons

Clock independently grades numeric normalization, zero-padding, signed multi-day updates,
reference-returning mutations, normalized equality and copy isolation. Formatting is
checked after noncanonical construction and updates as well as every in-day time. Bounded inputs avoid
integer overflow in the pinned reference. The public header is included before
probe helper headers, so missing dependencies and inconsistent members fail compilation.

Yacht checks all 7,776 ordered five-die rolls against an independent frequency
oracle for all 12 named categories, each with its own required verdict. Full houses require distinct pair/triple
faces; four of a kind scores four times the face even with five matching dice;
straights require every specified face exactly once. Invalid dice and unknown
category strings are outside the task contract.

These additions target the September 9 eight-run outcomes: Clock 2/8 Pass@1
and 7/8 MEF; Yacht 0/8 Pass@1 and 7/8 MEF. Their original generalized tests
already reject the observed errors. These probes add broader semantic coverage;
a benefit to model Pass@1 requires a new training/evaluation comparison.

Bank-account tests default/value construction in prefilled storage, then uses
an independent open/balance model for transaction sequences,
failed-operation preservation, reopening and object isolation. Dedicated valid-transaction
and rejected-state groups avoid rescoring reopening failures. Isolation compares
the untouched object before/after actions on the other object, without rechecking
the active object's local arithmetic/reset. Constructor member names are unrestricted. Parallel
transactions have scheduling-independent expected totals but are diagnostic
only; a clean sample does not prove race freedom. Zero amounts are excluded:
the instructions reject them while the reference accepts them. Concurrent
open/close and arithmetic overflow are not graded.

Circular-buffer uses a deque as an independent model, with int/string sequences
at capacities 1, 2, 3, 7 and 16, including overwrite, clear, rejected writes and
wraparound. A second caller translation unit instantiates long long and checks signed
values beyond 32 bits, catching int/string-only explicit instantiations and narrowed
storage. Zero capacity is excluded rather than inventing a rule.

Grade-school compares insertion orders and a fixed-seed 128-student sequence
with an independently sorted roster. Reads must agree without adding missing
grades or affecting other objects. Duplicates are excluded: the prose requires
rejection but the pinned reference inserts duplicates.

Allergies exhausts all 256 supported masks, checks each higher unsigned bit and
combined high bits, and compares individual membership with unordered lists.
Unknown allergen names and iteration order are not constrained.

Sublist adapts the existing specialist's independent exhaustive domain:
340 nonempty lists, 115,600 ordered pairs, lengths 1–4 over {-1,0,1,2}. Empty
inputs have their own group and are excluded from the relation/overlap groups. Longer overlapping
patterns, scattered nonmatches, swapped inputs and unchanged inputs supplement
that bounded exhaustive set. Equal/sublist/superlist/unequal relations, empty lists,
overlap cases and repeatability have separate verdicts. Repeatability checks
call stability, swap consistency and input immutability without repeating the
semantic oracle. Receipts use symbolic relation names. Additional lengths 31, 129
and 513 use disjoint large/negative values and repeated prefixes with late mismatches.

Space-age independently applies specified constants to zero, year boundaries,
wide unsigned seconds, scaling and repeated calls. The pinned 0.005 absolute
tolerance is preserved, with floating representation allowance at very large
magnitudes; exact equality is used only for original seconds.

Complex-numbers uses independent long-double arithmetic plus scalar orderings,
conjugation, magnitude, exponential and consistency relationships. Direct checks
use the pinned 0.005 tolerance; composed relationships allow accumulated error.
Direct and scalar addition/subtraction/multiplication/division each have independent
verdicts. Zero denominators and nonfinite inputs are excluded.

Dnd-character checks the complete 3–18 modifier table, ability ranges, and all
six character fields with independently calculated hitpoints. Negative odd, negative
even and nonnegative modifier inputs have separate verdicts. The separate
randomness observation warns about constant output without changing behavioral
status. It does not prove dice frequencies, prescribe an RNG, or require an
exact random sequence.

Perfect-numbers checks nonpositive-domain exceptions, unit/primes, known perfect
numbers, every positive number through 4,096, square boundaries, and deterministic
wide signed-int samples. Its oracle uses prime-factor divisor sums in 64-bit
arithmetic. The separate positive control uses divisor pairs. The pinned fixture
reference overflows at 2,000,000,000, so it is preserved and tested as a known
negative control for wide inputs. The replacement positive control is hash-bound
under `references/perfect-numbers`; it is never included in solver prompts.

## Evidence and validation

Reference and candidate JSON receipts contain commands, bounded logs, hashes,
reference health, group decisions, repeatability and source-immutability checks.
Failures include input/context, recent operation trace, expected/actual values
and the failed requirement. Build failures are not counted as semantic kills.
Reference failures invalidate the audit. No numerical GRPO reward is produced.

Validate the committed task registry, probe inventory and fixed reward-family
denominators without the separately staged trusted fixture bundle:

~~~sh
PYTHONPATH=src:. python3 Reward_GRPO/topic_coverage/self_check.py
~~~

## Execution boundary

Local execution requires explicit acknowledgement. Children receive a minimal
environment without HF/W&B credentials, have CPU/memory/output limits and wall
timeouts, and their process groups are cleaned up. The optional generalized
comparison has a larger 128 MiB file cap to accommodate Catch compilation.
This is not a security
sandbox: filesystem and network isolation must come from an existing isolated
worker/container before evaluating hostile code. Do not execute arbitrary model
outputs on a shared credential-bearing host.

Older packs have different bindings, compiler pins and receipt contracts.
This package reuses applicable behavioral ideas instead of blindly dispatching
every old policy or double-counting compilation and formatting. Changes to live
reward integration or task specifications require a separate decision.

## Requirement scoring in the combined reward

The standalone audit still returns verdicts without a numerical GRPO reward.
`scoring.py` validates complete receipts and computes the `topic-family-v3`
requirement fraction for the combined integration. Every group is all-or-nothing;
all groups run even after another group fails. Fractions are averaged within
families and then equally across families (64 groups, 39 families across eleven tasks).
The fixed family definitions live in `specs.py`. Assertion counts are never partial
credit: a fail-fast count includes the failing assertion and has no fixed denominator.
Diagnostics never contribute. Missing/duplicate/unknown groups or inconsistent
verdicts invalidate scoring. A candidate build failure has zero requirement credit.

The combined adapter gives positive reward only when both applicable layers pass.
For other completed topic audits it averages the nonpositive generalized score
and `topic_fraction - 1`. Thus a requirement repair increases reward while a
still-incorrect solution stays nonpositive. See the repository README for the combined generalized and targeted layout.
