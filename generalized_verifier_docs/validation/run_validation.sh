#!/usr/bin/env bash
# Reproduces every claim in VALIDATION.md. Run from the repo root:
#   bash generalized_verifier_docs/validation/run_validation.sh
# Requires: g++ (C++17), python3 stdlib. No network, no pip packages.
set -u
cd "$(dirname "$0")/.."            # -> generalized_verifier_docs/
GVD="$PWD"
FIX="$GVD/../Reward_GRPO/multi_env_fixtures"
CAND="$GVD/validation/candidates"
# The bank-account fixture (test file + .meta reference) is not part of
# Reward_GRPO/multi_env_fixtures; it ships inside the recorded eval receipts:
BA_FIX="/tmp/global_iter14_eval/trial-01/receipts/shard-0/2026-08-26-02-29-51--global-direct-iter14-fixed26-20260826-020704-trial-01-shard-0/cpp/exercises/practice/bank-account"

run() { echo; echo "\$ $*"; "$@" 2>&1; echo "[exit=$?]"; }
v01() { python3 "$GVD/01_structural_api_gate.py" "$@"; }
v03() { python3 "$GVD/03_two_stage_build_verifier.py" "$@"; }
v04() { python3 "$GVD/04_differential_semantic_verifier.py" "$@"; }

echo "############ A. Verifier 01 on recorded STRUCTURAL failures (expect FAIL)"
for i in 0 1 2 3 4; do
  run v01 --test "$FIX/binary-search-tree/binary_search_tree_test.cpp" \
          --header "$CAND/binary-search-tree/row$i.h" \
          --source "$CAND/binary-search-tree/row$i.cpp"
done
run v01 --test "$BA_FIX/bank_account_test.cpp" \
        --header "$CAND/bank-account/bank_account.h" \
        --source "$CAND/bank-account/bank_account.cpp"
run v01 --test "$FIX/kindergarten-garden/kindergarten_garden_test.cpp" \
        --header "$CAND/kindergarten-garden/kindergarten_garden.h" \
        --source "$CAND/kindergarten-garden/kindergarten_garden.cpp"
run v01 --test "$FIX/zebra-puzzle/zebra_puzzle_test.cpp" \
        --header "$CAND/zebra-puzzle/zebra_puzzle.h" \
        --source "$CAND/zebra-puzzle/zebra_puzzle.cpp"

echo; echo "############ B. Verifier 01 on reference implementations (expect PASS, 0 false positives)"
run v01 --test "$FIX/binary-search-tree/binary_search_tree_test.cpp" \
        --header "$FIX/binary-search-tree/.meta/example.h"
run v01 --test "$BA_FIX/bank_account_test.cpp" \
        --header "$BA_FIX/.meta/example.h" --source "$BA_FIX/.meta/example.cpp"
run v01 --test "$FIX/kindergarten-garden/kindergarten_garden_test.cpp" \
        --header "$FIX/kindergarten-garden/.meta/example.h" \
        --source "$FIX/kindergarten-garden/.meta/example.cpp"
run v01 --test "$FIX/zebra-puzzle/zebra_puzzle_test.cpp" \
        --header "$FIX/zebra-puzzle/.meta/example.h" \
        --source "$FIX/zebra-puzzle/.meta/example.cpp"
run v01 --test "$FIX/linked-list/linked_list_test.cpp" \
        --header "$FIX/linked-list/.meta/example.h" \
        --source "$FIX/linked-list/.meta/example.cpp"
run v01 --test "$FIX/crypto-square/crypto_square_test.cpp" \
        --header "$FIX/crypto-square/.meta/example.h" \
        --source "$FIX/crypto-square/.meta/example.cpp"

echo; echo "############ C. Verifier 01 must NOT flag non-structural failures"
run v01 --test "$FIX/linked-list/linked_list_test.cpp" \
        --header "$CAND/linked-list/linked_list.h" \
        --source "$CAND/linked-list/linked_list.cpp"
run v01 --test "$FIX/crypto-square/crypto_square_test.cpp" \
        --header "$CAND/crypto-square/crypto_square.h" \
        --source "$CAND/crypto-square/crypto_square.cpp"

echo; echo "############ D. Verifier 03: CE vs LE classification"
run v03 --fixture-dir "$FIX/binary-search-tree" \
        --header "$CAND/binary-search-tree/row0.h" \
        --source "$CAND/binary-search-tree/row0.cpp"
run v03 --fixture-dir "$FIX/linked-list" \
        --header "$CAND/linked-list/linked_list.h" \
        --source "$CAND/linked-list/linked_list.cpp"
run v03 --fixture-dir "$FIX/binary-search-tree" \
        --header "$FIX/binary-search-tree/.meta/example.h"

echo; echo "############ E. Verifier 04: differential semantic gate"
run v04 --fixture-dir "$FIX/crypto-square" \
        --header "$CAND/crypto-square/crypto_square.h" \
        --source "$CAND/crypto-square/crypto_square.cpp"
run v04 --fixture-dir "$FIX/crypto-square" \
        --header "$FIX/crypto-square/.meta/example.h" \
        --source "$FIX/crypto-square/.meta/example.cpp"
run v04 --fixture-dir "$FIX/kindergarten-garden" \
        --header "$CAND/kindergarten-garden-semantic/kindergarten_garden.h" \
        --source "$CAND/kindergarten-garden-semantic/kindergarten_garden.cpp"
run v04 --fixture-dir "$FIX/kindergarten-garden" \
        --header "$FIX/kindergarten-garden/.meta/example.h" \
        --source "$FIX/kindergarten-garden/.meta/example.cpp"

echo; echo "############ F. Litmus: no task names inside verifier logic"
# Scope: the three rewritten verifiers. 00/02/example_* are pre-existing demo
# files outside the rewrite scope (02 still contains its old hardcoded
# snippet by design; see VALIDATION.md).
grep -riE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants" \
  "$GVD/01_structural_api_gate.py" "$GVD/03_two_stage_build_verifier.py" \
  "$GVD/04_differential_semantic_verifier.py" \
  && echo "LITMUS: HITS FOUND" || echo "LITMUS: ZERO task-name hits"
