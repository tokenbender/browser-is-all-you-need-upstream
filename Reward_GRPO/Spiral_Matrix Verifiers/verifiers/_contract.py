
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='spiral-matrix',
    prefix='SM',
    source_files=('spiral_matrix.h', 'spiral_matrix.cpp'),
    implementation_files=('spiral_matrix.cpp',),
    fixed_hashes={'.docs/instructions.md': '9d5dff44082c7bac9e5ea721a58723f15d353cf9084885a98f7f00390c92bfb3', '.meta/config.json': '79cfa6b0c085e798d07b42c7732d39d637045c35016a34f4f8db1784b35d4cef', '.meta/tests.toml': 'a337f0493549c13b2a27d96924e742a9f99371da4235a25f5644cbcdb645b708', '.meta/example.h': '9a2a6a058c9e15453d895854ffade6e516f7a4f110e2c90bb0a4423b0e1f567f', '.meta/example.cpp': 'd2ee6f02fdd89facc7e0645cbc8d61ef81fc142b59eaab04c88893bebbf9a597', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'spiral_matrix_test.cpp': '406cce0e7cf16487fdd12df030bbf5fcfe57aeb36078c8eb13b16c1f8267239e'},
    test_file='spiral_matrix_test.cpp',
)
