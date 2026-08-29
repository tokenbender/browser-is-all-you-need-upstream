
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='complex-numbers',
    prefix='CX',
    source_files=('complex_numbers.h', 'complex_numbers.cpp'),
    implementation_files=('complex_numbers.cpp',),
    fixed_hashes={'.docs/instructions.md': '32d74988f93a781b3b27fc6750f4f41bcdf7b4d462904389d409e9ad606063fb', '.meta/config.json': '14edd9b7f0d96411138d757267a67a67ed853bfaa1a94daa2d90f7aef6b8082f', '.meta/tests.toml': '0dc04cbfa1c1ae0deadc9cf515a0dbf567159656528565816e284979e925c723', '.meta/example.h': 'c129b8a67bed8a94964d95592382de06b8c8510ebfb19aea996b8b45cc781bd0', '.meta/example.cpp': '690bd58562e2898bc3aeca8ea911b740f31ca2cf508ca2a4465bb80fa2f6440e', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'complex_numbers_test.cpp': '0bb911210fddcfe066825d5b562ca6efbf21d45386e62aebfd4693ad1b82897b'},
    test_file='complex_numbers_test.cpp',
)
