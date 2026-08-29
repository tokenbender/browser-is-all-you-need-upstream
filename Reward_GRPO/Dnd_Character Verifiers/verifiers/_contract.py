
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='dnd-character',
    prefix='DN',
    source_files=('dnd_character.h', 'dnd_character.cpp'),
    implementation_files=('dnd_character.cpp',),
    fixed_hashes={'.docs/instructions.md': 'ffe687063cba8152035fd35c859651f8d28d44db8ec5967b39e7145883360d74', '.meta/config.json': 'c8a2656325d47550fb977e6986afc12d48554bd009600f370b200cf88a8ff858', '.meta/tests.toml': 'c995b54cfc24dd3a5946bf2720d81ebbbfaed0fa3ddefa091a4fd5d2afe00201', '.meta/example.h': '7aa06621256ed069a24b771daf90b8124bf34c94cb18aabbf94724ba0d8dab2e', '.meta/example.cpp': '7de3a61604656aaabf9b797b34fc5760e5a1089bf23e47493e5ed213e7731e45', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'dnd_character_test.cpp': '0b90c2acf77f99986d73b5559e694a06627a53acf6034acf8c4b461ba7125f56'},
    test_file='dnd_character_test.cpp',
)
