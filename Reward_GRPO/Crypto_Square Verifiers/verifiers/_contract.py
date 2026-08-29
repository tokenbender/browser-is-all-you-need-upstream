
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='crypto-square',
    prefix='CS',
    source_files=('crypto_square.h', 'crypto_square.cpp'),
    implementation_files=('crypto_square.cpp',),
    fixed_hashes={'.docs/instructions.md': '1c64e2087dfbcfc0fafe2aa84009c24967c55d2533379e190ff5cc8aef987a63', '.meta/config.json': '88d40ad63709d6a61b75eb0e0686ed95c349ea627a2f080c68a542a85987b7dc', '.meta/tests.toml': 'da9b2b6969ee7c7615bb67d17fd2b8063c4ca69dffea623f6716ab7f44a0f9ce', '.meta/example.h': '68a55a978c9b32731299080e836440b0b951fc60caf1a2c7c8570091c2ea837b', '.meta/example.cpp': '1c4518aa7762df05163a2934a050df1c56201b19c98a5aa146681655b921099e', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'crypto_square_test.cpp': '3770199d92bda7e4551742ac2d5a30a1970318f18f92f29088f9704a6e67a676'},
    test_file='crypto_square_test.cpp',
)
