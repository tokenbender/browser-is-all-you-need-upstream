# Generalization Proof — Verifier 08: Safety Sanitizer Verifier (DIAGNOSTIC)

Every claim below comes from an actual run on this machine (Linux,
`g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` with
`-fsanitize=address,undefined`, python3 stdlib only). Reproduce:

```bash
python3 generalized_verifier_docs/validation/08/extract_cases.py   # regenerates cases/
bash    generalized_verifier_docs/validation/08/run_validation.sh  # 10/10 must print OK
```

(full transcript: `validation/08/transcript.txt`; outputs below were copied
from real runs verbatim). The verifier runs standalone:
`python3 generalized_verifier_docs/08_safety_sanitizer_verifier.py --help`.

## 1. Category definition

**Dynamic memory-safety / undefined-behavior diagnosis.** A candidate that
passes the strict build (G02) can still crash or invoke undefined behavior
when the official test executes it. Before this verifier, the eval and
training pipelines saw only an opaque "Segmentation fault (core dumped)" or
a Catch2 `SIGSEGV` test failure — indistinguishable from wrong logic, with
no attribution of *why* or *where*. This verifier rebuilds the candidate
against the task's pinned official test with AddressSanitizer +
UndefinedBehaviorSanitizer
(`-fsanitize=address,undefined -fno-sanitize-recover=all`), runs the
instrumented binary, and classifies the outcome from the sanitizer's own
report: `heap-buffer-overflow` / `stack-buffer-overflow` /
`global-buffer-overflow` / `heap-use-after-free` / `stack-use-after-return`
/ `stack-overflow` / `SEGV` / `null-deref` / `undefined-behavior` (with the
UBSan `runtime error` detail), plus the first stack frame inside a
candidate file.

It is a **DIAGNOSTIC policy**: it never adds a penalty on top of the
functional one (see §4), and its verdict comes from dynamic behavior only —
no source-text pattern decides it (the single static check is the
anti-exploit control in §5, which guards the verifier, not the task).

## 2. Evidence first (quoted, with paths), before any code was written

Recorded crashes from the pinned evidence tree (never modified; extraction
copies live in `validation/08/cases/`). `catch.hpp` contains boilerplate
SIGSEGV strings, so only make/test-output crash lines are counted:

| # | Recorded crash (verbatim) | Source (path:line) |
|---|---|---|
| 1 | `make[2]: *** [CMakeFiles/test_spiral-matrix.dir/build.make:70: CMakeFiles/test_spiral-matrix] Segmentation fault (core dumped)` (test output: `spiral-matrix is a Catch v2.13.6 host application. ... spiral of size 2 ... FAILED: due to a fatal error condition: SIGSEGV - Segmentation violation signal`) | `evidence/global_iter14_eval/trial-01/receipts/shard-1/2026-08-26-02-29-42--global-direct-iter14-fixed26-20260826-020704-trial-01-shard-1/cpp/exercises/practice/spiral-matrix/.aider.chat.history.md:535` (SIGSEGV at :529) |
| 2 | same make crash line, spiral-matrix trial-03 | `.../trial-03/receipts/shard-1/2026-08-26-02-39-18--.../spiral-matrix/.aider.chat.history.md:511` (SIGSEGV at :505) |
| 3 | same make crash line, spiral-matrix trial-04 | `.../trial-04/receipts/shard-1/2026-08-26-03-27-49--.../spiral-matrix/.aider.chat.history.md:541` (SIGSEGV at :535) |
| 4 | `/aider/parallel-letter-frequency/parallel_letter_frequency_test.cpp:23: FAILED: due to a fatal error condition: SIGSEGV - Segmentation violation signal` + `make[2]: *** [...test_parallel-letter-frequency] Segmentation fault (core dumped)` | `.../trial-03/receipts/shard-1/2026-08-26-02-39-18--.../parallel-letter-frequency/.aider.chat.history.md:1402-1408` |
| 5 | `1× SIGSEGV: u22/s5825 (due to a fatal error condition: SIGSEGV)` (training side, GRPO rollout row) | `evidence/global_direct_grpo30_audit/flow_zebra-puzzle.md:87` and `:131`; candidate already extracted at `evidence/global_direct_grpo30_audit/zebra_case/cand_u22_s5825/` |

So the need is recorded on **3 distinct tasks** (spiral-matrix ×3 trials,
parallel-letter-frequency, zebra-puzzle), on **both** sides of the pipeline
(checkpoint eval and GRPO training rollouts).

## 3. Error shape, task-independently

The classification keys on the *sanitizer runtimes'* fixed report format, a
property of the toolchain, not of any task:

```
==PID==ERROR: AddressSanitizer: <kind> on address ...        (memory errors)
==PID==ERROR: AddressSanitizer: SEGV on unknown address 0x... (deadly signal)
<file>:<line>:<col>: runtime error: <message>                 (UBSan)
SUMMARY: (Address|UndefinedBehavior)Sanitizer: <kind> <file>:<line> ...
    #N 0x... in <func> <path>:<line>                          (stack frames)
```

`null-deref` is `SEGV on unknown address` with a sub-page address
(`< 0x1000`); every other `AddressSanitizer:` kind string is passed through
verbatim, so kinds this validator never saw (e.g. `heap-use-after-free`)
still classify correctly. `candidate_location` is the first stack frame
whose file basename is a candidate file — workspace-independent by
construction. Zero task names in the engine; all task knowledge enters via
`--fixture-dir` / `--header` / `--source`.

## 4. Verdict taxonomy and exit-code ownership (diagnostic rule)

| Verdict | Meaning | Exit | Penalty owner |
|---|---|---|---|
| CLEAN | ran; no sanitizer report (functional outcome is a recorded FACT) | 0 | functional score: G03 |
| SANITIZER_HIT | ASan/UBSan fired; kind + first candidate frame reported | 1 | **G07 (unique signal)** |
| CRASH_NO_REPORT | signal death with no sanitizer report | 1 | **G07** |
| BUILD_FAIL | sanitized build failed | 0 | G02 |
| TIMEOUT | test binary exceeded the run timeout | 0 | G03/G04 timeout handling |
| INVALID | unusable input, or `sanitizer_suppression_attempt` | 2 | — |

Ownership matrix (non-conflict rule): **G01 owns structure, G02 owns build,
G03 owns the functional score, G04 response integrity, G05 boundary, G06
hygiene, G07 (this one) owns safety DIAGNOSIS.** If the candidate crashes or
fails functionally, the functional policy owns the −1; this verifier
classifies WHY without adding a second negative. Mechanically the pack
wrapper (`verifier_07_safety.py`) emits every kernel with `kernel: 0` —
excluded from the receipt's `kernel_sum` and `maximum_kernel_sum` — and
marks the receipt `policy_role: "diagnostic"`. The wrapper still reports
`status: fail` and exits 1 on a safety finding, because a functionally
*passing* candidate that exhibits UB must be flaggable — that signal exists
nowhere else in the pack.

`ASAN_OPTIONS=detect_leaks=0` is set for the run: LeakSanitizer (part of
ASan on Linux) would report the Catch2 harness's and the standard library's
own still-reachable teardown allocations, which the candidate cannot
control — leak noise must not contaminate verdicts. Genuine memory errors
and UB are unaffected.

## 5. Anti-exploit control (verifier resistance, not a task requirement)

A candidate could blind this verifier by annotating its code with
sanitizer-suppression attributes. Before any build, the candidate files are
scanned (comments stripped, literals blanked — same lexical approach as
verifier 01) for `no_sanitize` (covers `__attribute__((no_sanitize(...)))`,
`__attribute__((no_sanitize_address))`, `[[gnu::no_sanitize...]]`, and any
`#pragma GCC ... no_sanitize` spelling) and
`disable_sanitizer_instrumentation`. A hit is INVALID with reason
`sanitizer_suppression_attempt` — validated below (case
`exploit_no_sanitize`). This is the only source-text inspection in the
verifier; it protects the instrument, it does not grade the task.

## 6. Validation runs (real, on this machine)

`extract_cases.py` lifts the last complete whole-file listings before each
recorded crash line (aider whole-file format; anchors in
`cases/expected.json`), copies the already-extracted zebra training
candidate verbatim, and splices the synthetic exploit control from the
pinned clock reference (labeled SYNTHETIC in the manifest). Real output:

```
$ bash generalized_verifier_docs/validation/08/run_validation.sh
OK   fault_spiral_trial-01                  verdict=SANITIZER_HIT    kind=SEGV                 exit=1 spiral_matrix.cpp:35
OK   fault_plf_trial-03                     verdict=SANITIZER_HIT    kind=SEGV                 exit=1 parallel_letter_frequency.cpp:35
OK   fault_zebra_u22_s5825                  verdict=SANITIZER_HIT    kind=SEGV                 exit=1 zebra_puzzle.cpp:22
OK   reference_spiral-matrix                verdict=CLEAN            kind=None                 exit=0
OK   reference_parallel-letter-frequency    verdict=CLEAN            kind=None                 exit=0
OK   reference_zebra-puzzle                 verdict=CLEAN            kind=None                 exit=0
OK   reference_clock                        verdict=CLEAN            kind=None                 exit=0
OK   reference_allergies                    verdict=CLEAN            kind=None                 exit=0
OK   exploit_no_sanitize                    verdict=INVALID          kind=None                 exit=2
OK   functional_fail_crypto-square          verdict=CLEAN            kind=None                 exit=0

10/10 cases match expectations
```

Coverage:

- **Fault controls (3 recorded crashes, 3 tasks).** Each recorded crashing
  candidate reproduces as `SANITIZER_HIT` with kind and candidate location:
  spiral-matrix trial-01 (`SEGV`, `spiral_matrix.cpp:35` — the unsigned
  `uint32_t` loop index wraps below 0 and indexes the row vector wildly),
  parallel-letter-frequency trial-03 (`SEGV`,
  `parallel_letter_frequency.cpp:35` — `&text - texts.data()` subtracts the
  address of a by-value lambda parameter from the vector base),
  zebra-puzzle u22/s5825 (`SEGV`, `zebra_puzzle.cpp:22`).
- **Positive controls (5 references).** The three fault tasks'
  `.meta/example.*` plus two more families (clock, allergies): all `CLEAN`,
  all assertions passed, zero sanitizer findings — no task-package finding.
- **Exploit control.** The synthetic suppression candidate (passes trivially
  otherwise) is `INVALID`, exit 2, reason `sanitizer_suppression_attempt`.
- **Functional-fail-without-UB control.** The recorded wrong-logic
  crypto-square candidate (eval trial-02; Catch2 `"clu hlt io " ==
  "chillout "`) is `CLEAN`, exit 0, with the functional failure recorded as
  a fact owned by G03 — no penalty from this policy.

Sample real text outputs:

```
$ python3 generalized_verifier_docs/08_safety_sanitizer_verifier.py \
    --fixture-dir Reward_GRPO/multi_env_fixtures/zebra-puzzle \
    --header cases/fault_zebra_u22_s5825/zebra_puzzle.h \
    --source cases/fault_zebra_u22_s5825/zebra_puzzle.cpp
--- Safety Sanitizer Verifier (diagnostic) ---
VERDICT: SANITIZER_HIT
kind: SEGV
detail: SEGV on unknown address 0x03e8003f3593
candidate location: zebra_puzzle.cpp:22 in get_colors
functional (owned by G03, fact only): FAILED (0/1 assertions)
exit=1
```

```
=== functional_fail_crypto-square ===
VERDICT: CLEAN
note: no sanitizer report; any functional failure visible in 'functional' is owned by policy G03 and adds no penalty here
functional (owned by G03, fact only): FAILED (5/8 assertions)
exit=0
```

```
=== exploit_no_sanitize ===
VERDICT: INVALID
note: sanitizer_suppression_attempt
exit=2
```

Wrapper end-to-end (4-arg runner contract, real receipts):

```
$ python3 verifiers/verifier_07_safety.py --candidate-dir cases/fault_spiral_trial-01 \
    --manifest manifest.json --expected-manifest-sha256 <digest> --output-dir out
FAIL: safety finding: SANITIZER_HIT (SEGV) at spiral_matrix.cpp:35     (exit 1)
receipt: policy_id=G07 status=fail kernel_sum=0 maximum_kernel_sum=0
         policy_role="diagnostic"   <- finding recorded, semantic sum untouched

$ python3 verifiers/verifier_07_safety.py --candidate-dir cases/exploit_no_sanitize ...
INVALID: safety verifier: sanitizer_suppression_attempt                (exit 2)
receipt: status=invalid kernel_sum=None
```

Note the diagnostic wiring: even on a `fail` status the receipt's
`kernel_sum` is 0 and `maximum_kernel_sum` is 0 — G07 can never move the
semantic score.

## 7. Litmus

```
$ grep -icE "bankaccount|bank_account|crypto|chillout|cipher|binary_tree|binary-search|kindergarten|zebra|linked_list|linked-list|plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot|parallel|letter|grade|perfect|circular|complex|dnd|square|buffer" \
    generalized_verifier_docs/08_safety_sanitizer_verifier.py \
    "Reward_GRPO/Generalized Cpp Verifiers/verifiers/verifier_07_safety.py"
generalized_verifier_docs/08_safety_sanitizer_verifier.py:2
Reward_GRPO/Generalized Cpp Verifiers/verifiers/verifier_07_safety.py:0
```

The two engine hits are the ASan kind taxonomy itself — the docstring lines
enumerating `heap-buffer-overflow` / `stack-buffer-overflow` (the regex term
is `buffer`). Those name sanitizer *error classes* emitted by the toolchain
(the engine passes kind strings through verbatim), exactly as engine 03 keys
on the linker phrase `undefined reference`. Zero task names — including CLI
help text and arg names. Task names appear only in `validation/08/` (case
filenames, extractor anchors, this document) — input data, not verifier
logic.

## 8. Honest limitations

- **Runtime cost.** The sanitized build compiles the Catch2 harness with
  instrumentation (~20 s per case here, dominated by `tests-main.cpp`), and
  the instrumented binary is slower than a plain one. G07 is therefore a
  diagnosis layer to run alongside (or after) G03, not a replacement for
  the plain build.
- **Timeout interplay.** A candidate that hangs (e.g. unpruned brute force —
  5 recorded zebra-puzzle training rows timed out at the manifest's 300 s)
  yields TIMEOUT here with exit 0: hang handling stays with the functional
  policies' manifest timeout. The engine's own default run timeout is 120 s
  (`--timeout-seconds`), independent of any manifest timeout; consumers
  running G07 standalone should align it with their harness budget.
- **Compiler-version sanitizer behavior.** ASan/UBSan report wording is not
  an API and differs across gcc versions; kind parsing keys on the stable
  `ERROR: AddressSanitizer:` / `runtime error:` / `SUMMARY:` anchors, and an
  unrecognized kind degrades to passthrough of the verbatim kind string
  (still SANITIZER_HIT, never silently CLEAN). All validation here is
  gcc-13.3.0-only; the recorded eval crashes were produced under gcc 11.4
  without sanitizers, and this verifier reproduces them as sanitizer reports
  under 13.3 — the portability-probe question (multi-compiler eval) is
  deferred per the README note: zero compiler-version-dependent failures
  exist in the recorded evidence (gcc-11.4-vs-13.3 reproduction found 0/10
  dependent cases), so reconsider only when multi-compiler eval evidence
  exists.
- **Not all UB is reachable by the pinned test.** The sanitizer only sees
  paths the official test executes; a CLEAN verdict means "no UB observed
  under the official test", not "the candidate is UB-free".
- **CRASH_NO_REPORT is a residual class.** Deaths that bypass both
  sanitizers (e.g. some stack-exhaustion modes, `abort()` without a report)
  are classified by signal only, with no location. Stack-overflow is usually
  caught by ASan (`stack-overflow` kind) and then classifies precisely.
- **The suppression scan is lexical, not semantic.** It strips comments and
  literals before matching, so a comment mentioning `no_sanitize` does not
  trip it; a sufficiently exotic spelling (e.g. constructed via the
  preprocessor) would. The control exists so the *common, documented*
  suppression spellings cannot blind the verifier; it is defense against the
  realistic exploit, not a formal guarantee.
