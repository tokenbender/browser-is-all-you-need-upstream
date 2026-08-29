#!/usr/bin/env bash
# Regenerate transcript_05.txt: real runs of verifier 05 against every
# fixture in validation/05/fixtures/ (see extract_fixtures.py for provenance),
# plus the --help smoke test.
set -u
cd "$(dirname "$0")/../../.."   # repo root
V=generalized_verifier_docs/05_response_integrity_verifier.py
F=generalized_verifier_docs/validation/05/fixtures
OUT=generalized_verifier_docs/validation/05/transcript_05.txt

{
echo "$ python3 $V --help"
python3 "$V" --help
echo
pass=0; fail=0
for meta in "$F"/*.meta.json; do
    fx="${meta%.meta.json}"
    name="$(basename "$fx")"
    [ "$name" = "_empty_answer" ] && continue
    expect="$(python3 -c "import json;print(json.load(open('$meta'))['expect'])")"
    answer="$(python3 -c "import json;print(json.load(open('$meta')).get('answer_file') or '')")"
    gt="$(python3 -c "import json;print(json.load(open('$meta')).get('gen_tokens') or '')")"
    mt="$(python3 -c "import json;print(json.load(open('$meta')).get('max_tokens') or '')")"
    args=(--response "$fx")
    [ -n "$answer" ] && args+=(--answer "$F/$answer")
    [ -n "$gt" ] && args+=(--gen-tokens "$gt" --max-tokens "$mt")
    echo "=================================================================="
    echo "FIXTURE: $name   (expect $expect)"
    python3 -c "import json;m=json.load(open('$meta'));print('source:',m['source']);print('note:',m['note'])"
    echo "$ python3 $V ${args[*]}"
    python3 "$V" "${args[@]}"
    got="$(python3 "$V" "${args[@]}" --json | python3 -c "import json,sys;print(json.load(sys.stdin)['verdict'])")"
    if [ "$got" = "$expect" ]; then echo "RESULT: PASS (got $got)"; pass=$((pass+1));
    else echo "RESULT: FAIL (got $got, expected $expect)"; fail=$((fail+1)); fi
    echo
done
echo "=================================================================="
echo "FIXTURES PASS: $pass  FAIL: $fail"
echo
echo "$ grep -iE 'bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot' $V"
grep -iE 'bankaccount|crypto|chillout|cipher|binary_tree|kindergarten|zebra|linked_list|Plants|diamond|clock|spiral|allergies|sublist|meetup|gigasecond|robot' "$V"
echo "LITMUS exit: $? (1 = zero hits)"
} 2>&1 | tee "$OUT"
