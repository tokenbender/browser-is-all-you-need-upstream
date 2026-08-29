#!/usr/bin/env bash
# Reproduce every verifier-06 validation run quoted in VALIDATION_06.md.
# Run from the repo root:  bash generalized_verifier_docs/validation/06/run_validation_06.sh
set -u
cd "$(dirname "$0")/../../.."   # repo root
GV=generalized_verifier_docs
C=$GV/validation/06/cases
FIX=Reward_GRPO/multi_env_fixtures

echo "### step 0: extract recorded cases from the GRPO-30 rollout dumps (torch, weights_only=True)"
python3 $GV/validation/06/extract_cases.py
echo "### step 0b: extract clean recorded-PASS responses from eval chat histories"
python3 $GV/validation/06/extract_clean_cases.py

run() {  # run <label> <response> <editable...> [template args...]
    local label=$1 resp=$2; shift 2
    echo; echo "### $label"
    python3 $GV/06_candidate_boundary_verifier.py --response "$resp" "$@"
    echo "exit=$?"
}

run "forbidden_file / meetup u1 s477"        $C/meetup__u1_s477.response.txt               --editable meetup.h --editable meetup.cpp
run "forbidden_file / linked-list u1 s433"   $C/linked-list__u1_s433.response.txt          --editable linked_list.h --editable linked_list.cpp
run "forbidden_file / kindergarten u2 s666"  $C/kindergarten-garden__u2_s666.response.txt  --editable kindergarten_garden.h --editable kindergarten_garden.cpp
run "forbidden_file / zebra u3 s798"         $C/zebra-puzzle__u3_s798.response.txt         --editable zebra_puzzle.h --editable zebra_puzzle.cpp
run "duplicate_file / meetup u0 s130"        $C/meetup__u0_s130.response.txt               --editable meetup.h --editable meetup.cpp
run "duplicate_file / linked-list u2 s530"   $C/linked-list__u2_s530.response.txt          --editable linked_list.h --editable linked_list.cpp
run "duplicate_file / kindergarten u18 s4788" $C/kindergarten-garden__u18_s4788.response.txt --editable kindergarten_garden.h --editable kindergarten_garden.cpp
run "duplicate_file / zebra u8 s2294"        $C/zebra-puzzle__u8_s2294.response.txt        --editable zebra_puzzle.h --editable zebra_puzzle.cpp
run "invalid_format / meetup u0 s240"        $C/meetup__u0_s240.response.txt               --editable meetup.h --editable meetup.cpp
run "invalid_format / kindergarten u2 s609"  $C/kindergarten-garden__u2_s609.response.txt  --editable kindergarten_garden.h --editable kindergarten_garden.cpp

echo; echo "### truncated header-only / zebra u0 s74 (OMITTED_FILLED + reconstruction)"
python3 $GV/06_candidate_boundary_verifier.py \
    --response evidence/global_direct_grpo30_audit/zebra_case/resp_u0_s74.txt \
    --editable zebra_puzzle.h --editable zebra_puzzle.cpp \
    --template zebra_puzzle.h=$FIX/zebra-puzzle/zebra_puzzle.h \
    --template zebra_puzzle.cpp=$FIX/zebra-puzzle/zebra_puzzle.cpp \
    --out-dir $GV/validation/06/reconstructed_zebra_u0_s74
echo "exit=$?"

echo; echo "### end-to-end: build the reconstructed set with verifier 03"
python3 $GV/03_two_stage_build_verifier.py --fixture-dir $FIX/zebra-puzzle \
    --header $GV/validation/06/reconstructed_zebra_u0_s74/zebra_puzzle.h \
    --source $GV/validation/06/reconstructed_zebra_u0_s74/zebra_puzzle.cpp | head -12

run "clean / space-age trial-01 turn-1 (recorded PASS)"   $C/clean__space-age__turn1.response.txt   --editable space_age.h --editable space_age.cpp
run "clean / phone-number trial-01 turn-1 (recorded PASS)" $C/clean__phone-number__turn1.response.txt --editable phone_number.h --editable phone_number.cpp

echo; echo "### agreement sweep (06 vs production parser on all cases)"
python3 $GV/validation/06/check_agreement.py

echo; echo "### litmus"
grep -inE "bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot" \
    $GV/06_candidate_boundary_verifier.py
echo "litmus exit=$? (1 = zero hits)"
