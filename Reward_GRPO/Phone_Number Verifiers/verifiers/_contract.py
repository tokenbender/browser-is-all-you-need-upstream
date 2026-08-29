
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='phone-number',
    prefix='PH',
    source_files=('phone_number.h', 'phone_number.cpp'),
    implementation_files=('phone_number.cpp',),
    fixed_hashes={'.docs/instructions.md': '688f8b8082ed60ea107cbddd6f0418ab512df3ab8c13db5ab39436987a41df3b', '.meta/config.json': '22cf8096d7a86f8695e94c5b26dcdd33cb6e8f3ee4e3934d75bd6254938baf7b', '.meta/tests.toml': 'fa03b7027d1d70e12aa49b4ee1a4c6c8ce6c3cb2998ecc3d8992f553675baea1', '.meta/example.h': 'a784915f3d720e71c7f0288f1b8a7ab023413be5a46d491ad3827d3dfcdbe0a7', '.meta/example.cpp': '64019a0770afaca5378b1522ac9fbe8716a58bd54be1b45be19cdb2897ff4f5e', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'phone_number_test.cpp': '12aa1d8ef503b67d9be8a6d1b8bc858eabcc88af3db916821ec25dcb3709fee5'},
    test_file='phone_number_test.cpp',
)
