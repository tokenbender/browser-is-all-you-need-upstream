
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='circular-buffer',
    prefix='CB',
    source_files=('circular_buffer.h', 'circular_buffer.cpp'),
    implementation_files=('circular_buffer.cpp',),
    fixed_hashes={'.docs/instructions.md': '8501cd0234269a91f04d4c0c8aa1f7a1ee7896db4fd365a2743c5928df769134', '.meta/config.json': 'd1bfc326d8bc6cb667178fa3e0f3bb54936dabb1bdbca4b1457af5c669899267', '.meta/tests.toml': '207f98e15025b5055c482f8825147a0b46fca3940e3a572f484d51399a6ef2bc', '.meta/example.h': '307efcf0054996ec57cfb802b93638e2649c22218f57d8abf630de587e696e58', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'circular_buffer_test.cpp': 'e96c023cf3ac88ded69a5306655cb4b9097da219642fcb99b58d84bdf59f8e80'},
    test_file='circular_buffer_test.cpp',
)
