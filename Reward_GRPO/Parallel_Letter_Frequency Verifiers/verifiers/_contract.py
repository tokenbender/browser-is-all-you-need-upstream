
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='parallel-letter-frequency',
    prefix='PL',
    source_files=('parallel_letter_frequency.h', 'parallel_letter_frequency.cpp'),
    implementation_files=('parallel_letter_frequency.cpp',),
    fixed_hashes={'.docs/instructions.md': '241b469203880134a8931c9df45f838a817a37430df5f02267ee3cf2ebf57ba5', '.docs/instructions.append.md': '8b887d149f65a5170bd5a8025e327baca68040230aa373e6670e35be6155f466', '.meta/config.json': 'ffc01914a6b6e423bd3afbc4f3bfec1466719cd6637912841858297230281797', '.meta/tests.toml': 'e5744e988dda9d5bd2704300eea115158fef583467dbf06f833dfdbe6d46205e', '.meta/example.h': '1f3568d440bfe03539f67dca84e219a5f671a525e759621448cbde8a83d99af1', '.meta/example.cpp': 'e614c4aaa665c192f609c5e0571ddfff1660c65574d5301214b192893812b447', 'CMakeLists.txt': '0de539bc50df4f71f031cede0b5470b82298ff10892affc601b85d53b75471e6', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'parallel_letter_frequency_test.cpp': '9f0625d18d5ad5a04136c92d3064456a3c3e9e7847f4810f0c75f6d9db49ea5e'},
    test_file='parallel_letter_frequency_test.cpp',
)
