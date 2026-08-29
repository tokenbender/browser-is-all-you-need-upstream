
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='robot-name',
    prefix='RN',
    source_files=('robot_name.h', 'robot_name.cpp'),
    implementation_files=('robot_name.cpp',),
    fixed_hashes={'.docs/instructions.md': 'b2750750beea61e12bd1828720d21718771bde4b809a62582361be11cc68b2f7', '.meta/config.json': 'a034a2e4b27f5c2e8dc2ad151dd1b76afeba55e65f9e2add28767dfcc0a48718', '.meta/example.h': '0887f0ebd0fe974d16e11dc24eeeadc5d936821cddfad13e996387e2ec74fa44', '.meta/example.cpp': '7723754d4c589fb896145ce76990051474da3b4d2a05e1d0f1f986c792a54e95', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'robot_name_test.cpp': 'a61980d1065cad95bba9e8042e46fca8890b782367767a2a0e4b9c856de58fd5'},
    test_file='robot_name_test.cpp',
)
