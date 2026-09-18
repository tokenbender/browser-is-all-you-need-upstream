# Perfect Numbers positive control

This independently written control uses 64-bit divisor-pair accumulation and the
pinned public API. The topic oracle uses prime-factor divisor sums instead.

The pinned `.meta/example.cpp` remains unchanged: its `int` accumulation overflows
for input 2,000,000,000, whose proper-divisor sum is 2,997,558,082 (abundant).
The control catalog deliberately evaluates that original implementation as a
negative wide-arithmetic control. The corrected control, oracle, and source
hashes are included in the reward image digest and audit receipts. Neither
implementation is included in the training prompt.
