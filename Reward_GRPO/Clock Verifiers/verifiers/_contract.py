
from strange_cpp import Contract


CONTRACT = Contract(
    task_id='clock',
    prefix='CL',
    source_files=('clock.h', 'clock.cpp'),
    implementation_files=('clock.cpp',),
    fixed_hashes={'.docs/instructions.md': '878669626ebe9c4e368e358e79e2ad94ab95dec3760a74afdce9869b14c9fe37', '.meta/config.json': 'eaec15b4184cfe4a1fdc69caf12cabf62689adb1086ac141d704bbdecb18f9ac', '.meta/tests.toml': 'b084ed9ab7fe118408a48232e53b412ab5c98c2878481efe165d5b0a5adffe57', '.meta/example.h': '74bb7ea77a1a11a856065976fbc421da450112df5e38e232b83c63e072c60c62', '.meta/example.cpp': 'f269249dfeae1939942a7f3335d9f058e8e1c0de7e74205d7cb44eb1d5822269', 'CMakeLists.txt': '53d531120e650972adf19a2a42aa2d5bc716c93700ffac74c1c2868fdce633ff', 'test/catch.hpp': '681e7505a50887c9085539e5135794fc8f66d8e5de28eadf13a30978627b0f47', 'test/tests-main.cpp': '5847fda35c1320d94f8d088aaf34229d689f66f1da235f885cbb28c8f17e4260', 'clock_test.cpp': 'beb75d18d0db5458d7c6e38f506b503a497a6200c0169d2bdc6a913df8254d69'},
    test_file='clock_test.cpp',
)
