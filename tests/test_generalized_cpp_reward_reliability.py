"""Regressions for the September 10 GRPO verifier abort and lost evidence."""
import asyncio
import errno
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from Reward_GRPO import generalized_cpp_topic_grpo as reward


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv('MILES_RUN_ROOT', str(tmp_path))
    monkeypatch.setenv('GENERALIZED_CPP_REWARD_WORKERS', '2')
    monkeypatch.delenv('GENERALIZED_CPP_FAILURE_DIR', raising=False)
    monkeypatch.setattr(reward, '_SCORING_POOL', None)
    yield
    if reward._SCORING_POOL is not None:
        reward._SCORING_POOL[2].shutdown(wait=True, cancel_futures=True)


def bad():
    return dict(problem_id='complex-numbers', sample_index=42, score=0., reward=0.,
                infrastructure_error=True, reason='verifier_invalid', policy_results=[
                    dict(policy_id='G02', status='invalid', reason='compiler unavailable',
                         stderr_tail='compiler diagnostic retained')])


def sample():
    return dict(metadata={'problem_id': 'complex-numbers'}, response='complete source text',
                index=42, rollout_id=7)


@pytest.mark.parametrize('mode', ['single', 'list', 'mixed', 'two_loops'])
@pytest.mark.parametrize('worker_count', [2, 24])
def test_worker_limit_is_shared_across_call_shapes(mode, worker_count, monkeypatch):
    monkeypatch.setenv('GENERALIZED_CPP_REWARD_WORKERS', str(worker_count))
    active = peak = 0
    lock = threading.Lock()
    def score(item):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.015)
        with lock:
            active -= 1
        return dict(score=-.65, infrastructure_error=False)
    monkeypatch.setattr(reward, 'score_sample', score)
    async def run():
        calls = [] if mode == 'list' else [reward.reward_func(None, sample()) for _ in range(24)]
        if mode == 'list':
            calls = [reward.reward_func(None, [sample() for _ in range(24)])]
        if mode == 'mixed':
            calls.append(reward.reward_func(None, [sample() for _ in range(24)]))
        return await asyncio.gather(*calls)
    if mode == 'two_loops':
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: asyncio.run(run()), range(2)))
    else:
        asyncio.run(run())
    assert peak == worker_count and active == 0


def test_cancellation_keeps_physical_limit_and_failed_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('GENERALIZED_CPP_REWARD_WORKERS', '1')
    started, release = threading.Event(), threading.Event()
    count = 0
    def score(item):
        nonlocal count
        count += 1
        if count == 1:
            started.set()
            assert release.wait(5)
            return bad()
        return dict(score=1., infrastructure_error=False)
    monkeypatch.setattr(reward, 'score_sample', score)
    async def run():
        first = asyncio.create_task(reward.reward_func(None, sample()))
        assert await asyncio.to_thread(started.wait, 3)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(reward.reward_func(None, sample()))
        try:
            await asyncio.sleep(.05)
            assert count == 1
        finally:
            release.set()
        assert (await second)['score'] == 1.
    asyncio.run(run())
    files = list((tmp_path / 'reward_failures').glob('*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text())['record']['reason'] == 'verifier_invalid'


def test_all_failed_attempts_are_preserved_and_no_reward_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(reward, 'score_sample', lambda item: bad())
    with pytest.raises(reward.RewardInfrastructureError, match='no reward returned') as error:
        asyncio.run(reward.reward_func(None, sample()))
    files = sorted((tmp_path / 'reward_failures').glob('*.json'))
    assert len(files) == 3 and 'G02' in str(error.value)
    for number, path in enumerate(files, 1):
        data = json.loads(path.read_text())
        assert data['attempt'] == number
        assert data['sample'] == reward.sample_dict(sample())
        assert data['response_sha256'] == hashlib.sha256(sample()['response'].encode()).hexdigest()
        assert data['record']['policy_results'][0]['stderr_tail'] == 'compiler diagnostic retained'
        assert str(path) in str(error.value)
    assert not list((tmp_path / 'reward_failures').glob('*.tmp'))


def test_recovery_keeps_failed_attempt_receipts(tmp_path, monkeypatch):
    results = iter([bad(), bad(), dict(score=1., infrastructure_error=False)])
    monkeypatch.setattr(reward, 'score_sample', lambda item: next(results))
    record = asyncio.run(reward.reward_func(None, sample()))
    assert record['reward'] == 1 and record['infrastructure_attempts'] == 3
    assert len(record['infrastructure_failure_receipts']) == 2
    assert all(Path(p).is_file() for p in record['infrastructure_failure_receipts'])


def test_persistence_failure_never_fabricates_reward(monkeypatch):
    monkeypatch.setattr(reward, 'score_sample', lambda item: bad())
    def no_space(*args):
        raise OSError('disk full')
    monkeypatch.setattr(reward, '_save_failed_attempt', no_space)
    with pytest.raises(reward.RewardInfrastructureError, match='Cannot preserve'):
        asyncio.run(reward.reward_func(None, sample()))


def test_unexpected_scorer_exception_is_preserved(tmp_path, monkeypatch):
    def crash(item):
        raise RuntimeError('unexpected compiler bridge failure')
    monkeypatch.setattr(reward, 'score_sample', crash)
    with pytest.raises(reward.RewardInfrastructureError):
        asyncio.run(reward.reward_func(None, sample()))
    files = list((tmp_path / 'reward_failures').glob('*.json'))
    assert len(files) == 3
    assert 'unexpected compiler bridge failure' in json.loads(files[0].read_text())['record']['exception']


@pytest.mark.parametrize('mode', ['nonzero', 'timeout', 'cleanup'])
def test_worker_errors_keep_diagnostics(mode, monkeypatch):
    monkeypatch.setattr(reward, 'contract_digest', lambda: 'test')
    monkeypatch.setattr(reward, 'docker_command', lambda name: ['docker', 'run'])
    monkeypatch.setattr(reward, 'image_identity', lambda: 'sha256:test')
    def run(command, **kwargs):
        if command[:2] == ['docker', 'rm']:
            if mode == 'cleanup':
                raise OSError('docker cleanup unavailable')
            return SimpleNamespace(returncode=1, stderr='No such container', stdout='')
        if mode == 'timeout':
            raise subprocess.TimeoutExpired(command, 900, stderr=b'last diagnostic')
        result = dict(problem_id='complex-numbers', reward_contract=reward.CURRICULUM,
                      score=1., infrastructure_error=False)
        return SimpleNamespace(returncode=137 if mode == 'nonzero' else 0,
                               stderr='worker diagnostic', stdout=json.dumps(result))
    monkeypatch.setattr(reward.subprocess, 'run', run)
    item = sample()
    item['metadata']['combined_reward_sha256'] = 'test'
    result = reward.score_sample(item)
    assert result['infrastructure_error']
    if mode == 'timeout':
        assert result['worker']['timed_out'] and result['worker']['stderr_tail'] == 'last diagnostic'
    elif mode == 'nonzero':
        assert result['worker']['returncode'] == 137
        assert result['worker']['stderr_tail'] == 'worker diagnostic'
    else:
        assert 'cleanup unavailable' in result['worker']['cleanup_error']


@pytest.fixture
def engine():
    path = reward.ROOT / 'generalized_verifier_docs/03_two_stage_build_verifier.py'
    spec = importlib.util.spec_from_file_location('build_reliability', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tiny_build(tmp_path):
    root = tmp_path / 'fixture'
    (root / 'test').mkdir(parents=True)
    (root / 'tiny_test.cpp').write_text('#include "tiny.h"\nint run_tests(){return value()==7?0:1;}\n')
    (root / 'test/tests-main.cpp').write_text('int run_tests(); int main(){return run_tests();}\n')
    (root / 'tiny.h').write_text('#pragma once\nint value();\n')
    (root / 'tiny.cpp').write_text('#include "tiny.h"\nint value(){return 7;}\n')
    return root


@pytest.mark.parametrize('kind', ['separate', 'inline', 'duplicate', 'missing'])
def test_real_multitu_link_classification(engine, tiny_build, kind):
    root = tiny_build
    if kind in {'inline', 'duplicate'}:
        (root / 'tiny.h').write_text('#pragma once\n' + ('inline ' if kind == 'inline' else '') +
                                    'int value(){return 7;}\n')
        (root / 'tiny.cpp').write_text('#include "tiny.h"\n')
    elif kind == 'missing':
        (root / 'tiny.cpp').write_text('#include "tiny.h"\n')
    result = engine.build_candidate(str(root), str(root / 'tiny.h'), str(root / 'tiny.cpp'))
    try:
        if kind in {'separate', 'inline'}:
            assert result.status == 'PASS'
            assert subprocess.run([result.binary], check=False).returncode == 0
        else:
            assert result.status == 'LE'
            assert result.failure_kind == ('duplicate_definition' if kind == 'duplicate' else 'undefined_reference')
            if kind == 'duplicate':
                assert 'inline' in result.feedback and 'Missing definitions' not in result.feedback
            else:
                assert 'namespace and signature' in result.feedback
    finally:
        if result.workspace:
            shutil.rmtree(result.workspace)


@pytest.mark.parametrize('kind', ['missing_compiler', 'timeout', 'signal', 'tool_error', 'unknown_link'])
def test_toolchain_failures_remain_infrastructure(engine, tiny_build, monkeypatch, kind):
    real_run = engine.subprocess.run
    def run(command, **kwargs):
        if kind == 'missing_compiler':
            raise FileNotFoundError('compiler absent')
        if kind == 'timeout':
            raise subprocess.TimeoutExpired(command, 300, stderr=b'compile diagnostic')
        if kind == 'signal':
            return SimpleNamespace(returncode=-9, stderr='')
        if kind == 'tool_error':
            return SimpleNamespace(returncode=1, stderr='g++: fatal error: Killed signal terminated program cc1plus')
        if '-pthread' in command:
            return SimpleNamespace(returncode=1, stderr='/usr/bin/ld: unknown tool failure')
        return real_run(command, **kwargs)
    monkeypatch.setattr(engine.subprocess, 'run', run)
    result = engine.build_candidate(str(tiny_build), str(tiny_build/'tiny.h'), str(tiny_build/'tiny.cpp'))
    try:
        assert result.status == 'ERROR'
        assert result.failure_kind in {'compiler_unavailable', 'compiler_timeout', 'toolchain_failure', 'unclassified_link_failure'}
        if kind == 'timeout':
            assert result.stderr == 'compile diagnostic'
    finally:
        if result.workspace:
            shutil.rmtree(result.workspace)


def test_g03_never_hides_candidate_tool_failure(tiny_build, monkeypatch):
    pack = reward.ROOT / 'Reward_GRPO/Generalized Cpp Verifiers/verifiers'
    spec = importlib.util.spec_from_file_location('g03_reliability', pack/'verifier_03_differential_semantic.py')
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    (tiny_build/'.meta').mkdir()
    (tiny_build/'.meta/example.h').write_text('int value();')
    report = {'reference': {'status': 'OK'}, 'candidate': {'status': 'BUILD_FAIL',
              'build': {'status': 'ERROR', 'feedback': 'compiler unavailable',
                        'stderr_tail': 'lost compiler process'}}}
    monkeypatch.setattr(wrapper.common, 'run_engine', lambda *args, **kwargs: dict(
        return_code=1, stdout=json.dumps(report), stderr='', command=['engine'], duration_seconds=.1))
    kernels, status, reason = wrapper.run_checks(SimpleNamespace(candidate_dir=str(tiny_build)),
        {'fixture_dir': str(tiny_build), 'candidate_files': ['tiny.h', 'tiny.cpp']})
    assert status == 'invalid' and kernels[-1]['status'] == 'invalid'
    assert kernels[-1]['facts']['candidate']['build']['stderr_tail'] == 'lost compiler process'


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, reward.ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def semantic():
    return load_module('semantic_reliability',
                       'generalized_verifier_docs/04_differential_semantic_verifier.py')


@pytest.fixture
def semantic_fixture(tiny_build):
    root = tiny_build
    (root / '.meta').mkdir()
    for suffix in ('h', 'cpp'):
        shutil.copy2(root / f'tiny.{suffix}', root / f'.meta/example.{suffix}')
    (root / 'test/tests-main.cpp').write_text(
        '#include <cstdio>\nint run_tests();\nint main(){\n'
        'const int result=run_tests();\n'
        'std::puts(result ? "assertions: 2 | 1 passed | 1 failed" : '
        '"All tests passed (2 assertions in 1 test case)");\nreturn result;\n}\n')
    return root


@pytest.mark.parametrize('kind', ['good', 'wrong', 'forged_exit_zero', 'forged_exit_one',
                                  'forged_exit_exact', 'forged_return', 'loader_exit', 'resource_crash',
                                  'crash', 'compile', 'link'])
def test_g03_real_execution_requires_official_completion(semantic, semantic_fixture, kind):
    root = semantic_fixture
    bodies = {
        'good': 'return 7;',
        'wrong': 'return 8;',
        'forged_exit_zero': 'std::puts("All tests passed (999 assertions in 1 test case)"); '
                            'std::fflush(stdout); std::_Exit(0);',
        'forged_exit_one': 'std::puts("All tests passed (999 assertions in 1 test case)"); '
                           'std::fflush(stdout); std::_Exit(1);',
        'forged_exit_exact': 'std::puts("All tests passed (2 assertions in 1 test case)"); '
                             'std::fflush(stdout); std::_Exit(0);',
        'forged_return': 'std::puts("All tests passed (999 assertions in 1 test case)"); return 8;',
        'loader_exit': 'std::fputs("probe: error while loading shared libraries: missing.so\\n", stderr); '
                       'std::fflush(stderr); std::_Exit(127);',
        'resource_crash': 'std::fputs("std::system_error: Resource temporarily unavailable\\n", stderr); '
                          'std::fflush(stderr); std::raise(SIGABRT); return 8;',
        'crash': 'std::raise(SIGSEGV); return 8;',
        'compile': 'this is not C++;',
    }
    code = '#include "tiny.h"\n#include <cstdio>\n#include <cstdlib>\n#include <csignal>\n'
    if kind != 'link':
        code += 'int value(){' + bodies[kind] + '}\n'
    (root / 'tiny.cpp').write_text(code)
    report = semantic.verify(str(root), str(root/'tiny.h'), str(root/'tiny.cpp'))
    assert report['reference']['status'] == 'OK', report
    assert report['verdict'] == ('PASS' if kind == 'good' else 'FAIL'), report
    if kind in {'compile', 'link'}:
        assert report['candidate']['build']['status'] == ('CE-1' if kind == 'compile' else 'LE')
    else:
        run = report['candidate']['run']
        assert run['verified_pass'] is (kind == 'good')
        if kind.startswith('forged_exit'):
            assert not run['execution_completed'] and run['score'] == 0
        if kind in {'loader_exit', 'resource_crash'}:
            assert not run['execution_completed'] and not run['infrastructure_error']
            assert run['score'] == 0
        if kind == 'forged_exit_exact':
            assert run['total_assertions'] == report['reference']['run']['total_assertions'] == 2
        if kind == 'crash':
            assert run['failure_kind'] == 'signal' and run['signal'] == 11
    if kind != 'good':
        assert report['score'] < 1.0


@pytest.mark.parametrize('total', [1000000, 10**25])
def test_failed_fraction_never_rounds_to_full_score(semantic, total):
    run = semantic.parse_catch2_output(f'assertions: {total} | {total-1} passed | 1 failed', 1)
    run.execution_completed, run.harness_returncode = True, 1
    assert not run.verified_pass
    assert 0 < run.as_dict()['score'] < 1
    encoded = json.loads(json.dumps(run.as_dict()))
    assert encoded['score'] < 1
    from Reward_GRPO import generalized_cpp_grpo as base
    receipt = {'status': 'fail', 'policy_results': [{'policy_id': 'G03', 'kernels': [
        {'kernel_id': 'G03-2', 'status': 'fail', 'kernel': -1, 'facts': {
            'reference': {'status': 'OK'}, 'candidate': {'status': 'RAN', 'run': encoded}}}]}]}
    assert 0 < base._candidate_semantic_fraction(receipt) < 1
    assert base.receipt_to_reward(receipt)[0] <= 0
    for flag, invalid_value in [('execution_completed', False), ('infrastructure_error', True),
                                ('timed_out', True), ('crashed', True)]:
        saved = encoded[flag]
        encoded[flag] = invalid_value
        assert base._candidate_semantic_fraction(receipt) is None
        assert base.receipt_to_reward(receipt)[0] <= 0
        encoded[flag] = saved
    encoded['score'] = 1.0
    assert base._candidate_semantic_fraction(receipt) is None


@pytest.mark.parametrize('output,rc', [
    ('All tests passed (100 assertions in 1 test case)', 0),
    ('All tests passed (100 assertions in 1 test case)', 1),
    ('assertions: 100 | 100 passed', 0),
    ('assertions: 10 | 9 passed | 3 failed', 1),
    ('assertions: 10 | 9 passed | 1 failed\nAll tests passed (10 assertions in 1 test case)', 0),
    ('assertions: ' + '9' * 5000 + ' | 1 failed', 1),
])
def test_stdout_alone_never_establishes_pass(semantic, output, rc):
    run = semantic.parse_catch2_output(output, rc)
    assert not run.verified_pass and run.score == 0


@pytest.mark.parametrize('failure', ['missing', 'bad_reference', 'tool'])
def test_g03_reference_failure_is_invalid(semantic, semantic_fixture, monkeypatch, failure):
    root = semantic_fixture
    if failure == 'missing':
        (root / '.meta/example.h').unlink()
    elif failure == 'bad_reference':
        (root / '.meta/example.cpp').write_text('int value(){return 8;}')
    else:
        monkeypatch.setattr(semantic._twostage, 'CXX', '/no/such/compiler')
    report = semantic.verify(str(root), str(root/'tiny.h'), str(root/'tiny.cpp'))
    assert report['verdict'] == 'INVALID' and report['score'] == 0
    assert report['candidate']['status'] == 'NOT_RUN'


def test_g03_missing_runtime_is_infrastructure(semantic, tmp_path):
    run = semantic.run_test_binary(str(tmp_path/'absent'))
    assert run.as_dict()['infrastructure_error']
    assert run.as_dict()['failure_kind'] == 'runtime_launch_failure'
    assert not run.verified_pass


def test_g03_runtime_timeout_is_distinct(semantic, semantic_fixture):
    root = semantic_fixture
    (root/'tiny.cpp').write_text('int value(){for (;;) {} return 7;}')
    build = semantic.build_candidate(str(root), str(root/'tiny.h'), str(root/'tiny.cpp'),
                                     authenticate_main=True)
    try:
        assert build.status == 'PASS'
        run = semantic.run_test_binary(build.binary, timeout=.1, completion_token=build.completion_token)
        assert run.timed_out and run.as_dict()['failure_kind'] == 'runtime_timeout'
        assert not run.infrastructure_error and not run.verified_pass
    finally:
        shutil.rmtree(build.workspace)


@pytest.mark.parametrize('mode', ['rounded_failure', 'forged_success', 'infrastructure', 'malformed'])
def test_g03_wrapper_does_not_promote_score_to_pass(tiny_build, monkeypatch, mode):
    wrapper = load_module('g03_guard_reliability',
        'Reward_GRPO/Generalized Cpp Verifiers/verifiers/verifier_03_differential_semantic.py')
    (tiny_build/'.meta').mkdir()
    (tiny_build/'.meta/example.h').write_text('int value();')
    run = dict(score=1.0, passed_assertions=999999, total_assertions=1000000,
               execution_completed=True, harness_returncode=1, returncode=1, verified_pass=False)
    report = dict(reference={'status': 'OK'}, candidate={'status': 'RAN', 'run': run}, verdict='FAIL')
    if mode == 'forged_success':
        report['verdict'] = 'PASS'
        run.update(returncode=0, execution_completed=False)
    if mode == 'infrastructure':
        run['infrastructure_error'] = True
        report['verdict'] = 'INVALID'
    if mode == 'malformed':
        del run['verified_pass']
    monkeypatch.setattr(wrapper.common, 'run_engine', lambda *args: dict(
        return_code={'PASS': 0, 'FAIL': 1, 'INVALID': 2}[report['verdict']],
        stdout=json.dumps(report), stderr='diagnostic', command=['engine'], duration_seconds=.1))
    kernels, status, _ = wrapper.run_checks(SimpleNamespace(candidate_dir=str(tiny_build)),
        {'fixture_dir': str(tiny_build), 'candidate_files': ['tiny.h', 'tiny.cpp']})
    assert status == ('invalid' if mode in {'infrastructure', 'malformed'} else 'fail')
    assert kernels[-1]['kernel'] != 1


@pytest.mark.parametrize('filename', ['03_two_stage_build_verifier.py', '04_differential_semantic_verifier.py'])
def test_standalone_infrastructure_receipt_is_invalid(filename, semantic_fixture, tmp_path):
    import os
    import sys
    root = semantic_fixture
    proc = subprocess.run([sys.executable, '-B', str(reward.ROOT/'generalized_verifier_docs'/filename),
        '--fixture-dir', str(root), '--header', str(root/'tiny.h'), '--source', str(root/'tiny.cpp'),
        '--json', '--receipt', str(tmp_path/'receipt')], capture_output=True, text=True,
        env={**os.environ, 'CXX': '/no/such/compiler'}, timeout=20)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    receipt = json.loads(next((tmp_path/'receipt').glob('*.json')).read_text())
    assert receipt['status'] == 'invalid' and receipt['kernel_sum'] is None
    assert 'compiler' in receipt['kernel_results'][0]['facts']['stdout_tail']


@pytest.mark.parametrize('code,stderr,timed_out,launch,expected', [
    (-9, '', False, None, ('invalid', 'compiler_signal')),
    (1, 'g++: fatal error: Killed signal terminated program cc1plus', False, None,
     ('invalid', 'toolchain_failure')),
    (1, '/usr/bin/ld: unknown tool failure', False, None, ('invalid', 'unclassified_link_failure')),
    (1, '/usr/bin/ld: undefined reference to value()', False, None, ('fail', 'undefined_reference')),
    (1, '/usr/bin/ld: multiple definition of value()', False, None, ('fail', 'duplicate_definition')),
    (1, 'candidate.cpp:2: error: invalid syntax', False, None, ('fail', 'candidate_compile')),
    (-9, 'compile log', True, None, ('invalid', 'compiler_timeout')),
    (126, 'exec failed', False, 'missing compiler', ('invalid', 'compiler_invocation_failure')),
    (0, '', False, None, None),
])
def test_topic_build_attribution(code, stderr, timed_out, launch, expected):
    from Reward_GRPO.topic_coverage.runner import build_failure
    assert build_failure(dict(returncode=code, stderr_tail=stderr, timed_out=timed_out,
                              launch_error=launch)) == expected


@pytest.mark.parametrize('output,code,timed_out,status,reason', [
    ("terminate called after throwing an instance of 'std::system_error'\n"
     'what(): Resource temporarily unavailable', -6, False, 'fail', 'runtime_signal'),
    ('probe: error while loading shared libraries: libc.so: unavailable', 127, False,
     'fail', 'probe_protocol_failure'),
    ("FAILED: assertion\nstd::system_error Resource temporarily unavailable", -6, False,
     'fail', 'runtime_signal'),
    ('', -11, False, 'fail', 'runtime_signal'),
    ('', -9, True, 'fail', 'runtime_timeout'),
])
def test_topic_runtime_attribution(output, code, timed_out, status, reason):
    from Reward_GRPO.topic_coverage.runner import parse_result
    result = parse_result(dict(returncode=code, stdout_tail=output, stderr_tail='',
                               timed_out=timed_out), 'group')
    assert (result['status'], result['reason']) == (status, reason)


def test_topic_exec_error_channel_distinguishes_candidate_exit(tmp_path):
    import sys
    from Reward_GRPO.topic_coverage.runner import AuditSession, parse_result
    session = AuditSession.__new__(AuditSession)
    session.work = tmp_path
    missing = session._command(['/no/such/compiler'], tmp_path/'logs', 'missing', 5)
    assert 'FileNotFoundError' in missing['launch_error']
    assert parse_result(missing, 'group')['status'] == 'invalid'
    candidate = session._command([sys.executable, '-c', 'raise SystemExit(126)'],
                                 tmp_path/'logs', 'candidate', 5)
    assert candidate['returncode'] == 126 and not candidate.get('launch_error')
    assert parse_result(candidate, 'group')['status'] == 'fail'


def test_full_g07_manifest_accepted_by_schema_validator_and_runner(tmp_path):
    from jsonschema import Draft7Validator
    from Reward_GRPO import global_cpp_verifier_runner as runner
    pack = reward.ROOT / 'Reward_GRPO/Generalized Cpp Verifiers'
    validator = load_module('manifest_reliability',
                           'Reward_GRPO/Generalized Cpp Verifiers/verifiers/_manifest_validation.py')
    schema = json.loads((pack/'global_verifier_manifest.schema.json').read_text())
    manifest = dict(schema_version=1, task_id='synthetic-check', candidate_files=['tiny.h'],
                    policies={key: [] for key in runner.PROFILE_POLICIES['full']})
    assert 'G07' in manifest['policies']
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(manifest)
    validator.validate_manifest(manifest)
    candidate = tmp_path/'candidate'
    candidate.mkdir()
    (candidate/'tiny.h').write_text('int value();')
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    prepared = runner._prepare(SimpleNamespace(candidate_dir=candidate, manifest=path,
        reward_root=pack.parent, expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        profile='full'), tmp_path/'output')
    assert set(prepared.wrappers) == set(runner.PROFILE_POLICIES['full'])
    for policies in ({'G08': []}, {'G07': 'not an array'}):
        invalid = {**manifest, 'policies': policies}
        assert list(Draft7Validator(schema).iter_errors(invalid))
        with pytest.raises(validator.ManifestValidationError):
            validator.validate_manifest(invalid)
        path.write_text(json.dumps(invalid))
        with pytest.raises(runner.RunnerError, match='manifest validation failed'):
            runner._prepare(SimpleNamespace(candidate_dir=candidate, manifest=path,
                reward_root=pack.parent, expected_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                profile='full'), tmp_path/'invalid-output')


def test_stage_launch_is_not_exposed(monkeypatch, capsys):
    import sys
    assert not hasattr(reward, 'stage_launch')
    monkeypatch.setattr(sys, 'argv', ['combined-verifier', '--help'])
    with pytest.raises(SystemExit) as exit:
        reward.main()
    assert exit.value.code == 0
    assert 'stage-launch' not in capsys.readouterr().out
    monkeypatch.setattr(sys, 'argv', ['combined-verifier', 'stage-launch'])
    with pytest.raises(SystemExit) as exit:
        reward.main()
    assert exit.value.code == 2
    source = Path(reward.__file__).read_text()
    assert 'generalized_cpp_topic_grpo_skypilot.yaml' not in source
    assert 'charm_bridge_preflight' not in source


@pytest.mark.parametrize('forged', [False, True])
def test_g03_real_engine_wrapper_reward_path(semantic_fixture, forged):
    from Reward_GRPO import generalized_cpp_grpo as base
    wrapper = load_module('g03_live_reliability',
        'Reward_GRPO/Generalized Cpp Verifiers/verifiers/verifier_03_differential_semantic.py')
    root = semantic_fixture
    if forged:
        (root/'tiny.cpp').write_text('#include <cstdio>\n#include <cstdlib>\nint value(){'
            'std::puts("All tests passed (1000000 assertions in 1 test case)"); '
            'std::fflush(stdout); std::_Exit(0);}')
    kernels, status, _ = wrapper.run_checks(SimpleNamespace(candidate_dir=str(root)),
        {'fixture_dir': str(root), 'candidate_files': ['tiny.h', 'tiny.cpp']})
    receipt = {'status': status, 'policy_results': [{'policy_id': 'G03', 'kernels': kernels}]}
    value, infrastructure, _ = base.receipt_to_reward(receipt)
    assert status == ('fail' if forged else 'pass')
    # This isolated wrapper is not a complete aggregate and cannot establish
    # full reward. The full-runner test below covers the genuine PASS path.
    assert value <= 0
    assert infrastructure == (not forged)


def test_g02_real_missing_tool_diagnostics_survive_wrapper(semantic_fixture, monkeypatch):
    wrapper = load_module('g02_live_reliability',
        'Reward_GRPO/Generalized Cpp Verifiers/verifiers/verifier_02_two_stage_build.py')
    root = semantic_fixture
    monkeypatch.setenv('CXX', '/no/such/compiler')
    kernels, status, _ = wrapper.run_checks(SimpleNamespace(candidate_dir=str(root)),
        {'fixture_dir': str(root), 'candidate_files': ['tiny.h', 'tiny.cpp']})
    assert status == 'invalid'
    assert kernels[-1]['facts']['failure_kind'] == 'compiler_unavailable'
    assert '/no/such/compiler' in kernels[-1]['facts']['feedback']


def test_topic_compile_failure_keeps_existing_zero_credit_contract(tmp_path, monkeypatch):
    from Reward_GRPO.topic_coverage.runner import AuditSession
    from Reward_GRPO.topic_coverage.scoring import summarize_requirements
    from Reward_GRPO.topic_coverage.specs import TOPICS
    session = AuditSession.__new__(AuditSession)
    session.task_id, session.topic = 'sublist', TOPICS['sublist']
    session.work, session.output = tmp_path/'work', tmp_path/'output'
    session.work.mkdir()
    session.output.mkdir()
    session.compiler, session.compile_timeout = 'g++', 10
    session.binding = SimpleNamespace(manifest={'candidate_files': ['sublist.h', 'sublist.cpp']})
    monkeypatch.setattr(session, '_command', lambda *args: dict(returncode=1, timed_out=False,
        stderr_tail='candidate.cpp:1: error: invalid syntax', stdout_tail=''))
    result = session._execute({'sublist.h': '', 'sublist.cpp': 'invalid'}, 'candidate')
    assert result['status'] == 'fail' and result['failure_kind'] == 'candidate_compile'
    score = summarize_requirements('sublist', dict(reference_status='pass', status='fail', candidate=result))
    assert score['fraction'] == 0 and score['build_failed']


def test_g02_standalone_cleans_successful_build_workspace(engine, tiny_build, tmp_path, monkeypatch):
    workspace = tmp_path/'completed-build'
    workspace.mkdir()
    monkeypatch.setattr(engine, 'build_candidate', lambda *args: engine.BuildResult(
        'PASS', 2, 'built', workspace=str(workspace)))
    assert engine.run(SimpleNamespace(fixture_dir=str(tiny_build), header='', source=None, json=True)) == 0
    assert not workspace.exists()


@pytest.mark.parametrize('diagnostic', [
    'std::system_error: Resource temporarily unavailable',
    'probe: error while loading shared libraries: missing.so: unavailable',
])
@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_completed_topic_failure_outranks_candidate_text(tmp_path, diagnostic, stream):
    from Reward_GRPO.topic_coverage.runner import AuditSession, aggregate_group, parse_result
    session = AuditSession.__new__(AuditSession)
    session.work = tmp_path
    receipt = dict(protocol='topic-coverage-v1', group='group', status='fail', checks=2,
                   requirement='wrong value', expected=7, actual=8)
    script = ('import sys\n'
              f'print({diagnostic!r}, file=sys.{stream})\n'
              f'print({("TOPIC_COVERAGE_RECEIPT " + json.dumps(receipt))!r})\n'
              'raise SystemExit(1)\n')
    command = session._command([sys.executable, '-c', script], tmp_path/'logs', 'candidate', 5)
    assert command['returncode'] == 1 and not command.get('launch_error')
    assert diagnostic in command[f'{stream}_tail']
    assert command['runtime_diagnostic'] in {'runtime_loader_failure', 'runtime_resource_exhaustion'}
    result = parse_result(command, 'group')
    assert result['status'] == 'fail' and result['requirement'] == 'wrong value'
    assert aggregate_group('group', [result, result])['status'] == 'fail'


def test_g03_authoritative_resource_launch_failure_is_invalid(semantic, monkeypatch):
    def unavailable(*args, **kwargs):
        raise BlockingIOError(errno.EAGAIN, 'Resource temporarily unavailable')
    monkeypatch.setattr(semantic.subprocess, 'Popen', unavailable)
    run = semantic.run_test_binary('/candidate')
    assert run.infrastructure_error == 'runtime_resource_exhaustion' and not run.execution_completed
    assert not run.verified_pass and run.score == 0
    assert 'Resource temporarily unavailable' in run.raw_tail


def test_g03_timeout_with_descendant_held_pipe_is_bounded(semantic, semantic_fixture, tmp_path):
    """A supervisor deadline makes unbounded communicate fail, not hang pytest."""
    root = semantic_fixture
    pid_file = tmp_path / 'detached.pid'
    (root / 'tiny.cpp').write_text(
        '#include <cstdio>\n#include <unistd.h>\nint value(){\n'
        'if (fork() == 0) { setsid();\n'
        f'FILE* pid_file=std::fopen({json.dumps(str(pid_file))}, "w");\n'
        'if (!pid_file) _exit(90);\n'
        'std::fprintf(pid_file, "%ld", static_cast<long>(getpid())); std::fclose(pid_file);\n'
        'std::puts("descendant retains stdout/stderr"); std::fflush(stdout);\n'
        'sleep(30); _exit(0); }\n'
        'for (;;) { pause(); } return 7; }\n')
    build = semantic.build_candidate(str(root), str(root/'tiny.h'), str(root/'tiny.cpp'),
                                     authenticate_main=True)
    try:
        assert build.status == 'PASS', build.as_dict()
        script = '''import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location('drain_test', sys.argv[1])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
started = time.monotonic()
run = engine.run_test_binary(sys.argv[2], timeout=.2, completion_token=sys.argv[3])
print(json.dumps({'elapsed': time.monotonic() - started, 'run': run.as_dict()}))
'''
        # This fails within five seconds even if production draining regresses.
        proc = subprocess.run([sys.executable, '-B', '-c', script, semantic.__file__,
                               build.binary, build.completion_token],
                              capture_output=True, text=True, timeout=5)
        assert proc.returncode == 0, proc.stderr
        result = json.loads(proc.stdout)
        run = result['run']
        assert result['elapsed'] < 2.0, result
        assert run['timed_out'] and run['failure_kind'] == 'runtime_timeout'
        assert run['returncode'] == -signal.SIGKILL
        assert not run['infrastructure_error'] and not run['verified_pass'] and run['score'] == 0
        assert run['output_drain_timed_out'] and not run['cleanup_timed_out']
        assert 'descendant retains stdout/stderr' in run['raw_tail']
        assert pid_file.is_file()
        os.kill(int(pid_file.read_text()), 0)  # EOF is still held when the handler returns.
        print(f"bounded timeout: {result['elapsed']:.3f}s; assertion <2.0s; supervisor 5.0s")
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if build.workspace:
            shutil.rmtree(build.workspace)


@pytest.mark.parametrize('kind', ['good', 'forged_exact', 'forged_nonexact', 'loader_failure',
                                  'resource_failure'])
def test_g03_full_receipt_aggregation_reward_path(semantic_fixture, tmp_path, kind):
    from Reward_GRPO import generalized_cpp_grpo as base
    from Reward_GRPO import global_cpp_verifier_runner as runner
    root = semantic_fixture
    if kind.startswith('forged'):
        count = 2 if kind == 'forged_exact' else 1000000
        (root/'tiny.cpp').write_text('#include <cstdio>\n#include <cstdlib>\nint value(){'
            f'std::puts("All tests passed ({count} assertions in 1 test case)"); '
            'std::fflush(stdout); std::_Exit(0);}')
    elif kind.endswith('failure'):
        text = ('probe: error while loading shared libraries: missing.so' if kind == 'loader_failure'
                else 'std::system_error: Resource temporarily unavailable')
        (root/'tiny.cpp').write_text('#include <cstdio>\nint value(){'
                                    f'std::puts({json.dumps(text)}); return 8;}}')
    manifest = dict(schema_version=1, task_id='synthetic-check', fixture_dir=str(root),
        candidate_files=['tiny.h', 'tiny.cpp'], policies={f'G{i:02d}': [] for i in range(1, 6)},
        response_text='\n\n'.join(f'{name}\n```cpp\n{(root/name).read_text()}\n```'
                                    for name in ['tiny.h', 'tiny.cpp']))
    path, output = tmp_path/'manifest.json', tmp_path/'aggregate'
    path.write_text(json.dumps(manifest))
    code = runner.main(['--candidate-dir', str(root), '--manifest', str(path),
        '--expected-manifest-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--output-dir', str(output), '--reward-root', str(reward.ROOT/'Reward_GRPO'),
        '--profile', 'live'])
    receipt = json.loads((output/runner.AGGREGATE_RECEIPT).read_text())
    assert code == (0 if kind == 'good' else 1), receipt
    assert receipt['executed_policies'] == ['G01', 'G02', 'G03', 'G04', 'G05']
    policy = next(p for p in receipt['policy_results'] if p['policy_id'] == 'G03')
    facts = next(k for k in policy['kernels'] if k['kernel_id'] == 'G03-2')['facts']
    run = facts['candidate']['run']
    assert facts['engine_exit_code'] == (0 if kind == 'good' else 1)
    if kind == 'forged_exact':
        assert run['total_assertions'] == facts['reference']['run']['total_assertions'] == 2
    if kind.startswith('forged'):
        assert not run['execution_completed'] and not run['verified_pass']
    if kind.endswith('failure'):
        assert run['execution_completed'] and run['score'] == .5
        assert base._candidate_semantic_fraction(receipt) == .5
        assert text in run['raw_tail']
        assert run['runtime_diagnostic'] in {'runtime_loader_failure', 'runtime_resource_exhaustion'}
    value, infrastructure, _ = base.receipt_to_reward(receipt)
    assert not infrastructure
    assert receipt['status'] == ('pass' if kind == 'good' else 'fail')
    assert (value == 1) if kind == 'good' else (value <= 0)
    if kind == 'good':
        import copy
        for defect in ('missing_policy', 'broken_reference', 'malformed_kernels', 'missing_kernel_status'):
            malformed = copy.deepcopy(receipt)
            if defect == 'missing_policy':
                malformed['policy_results'] = [policy]
            elif defect == 'malformed_kernels':
                malformed['policy_results'][0]['kernels'] = None
            elif defect == 'missing_kernel_status':
                malformed['policy_results'][0]['kernels'][0].pop('status')
            else:
                semantic = next(p for p in malformed['policy_results'] if p['policy_id'] == 'G03')
                semantic['kernels'][-1]['facts']['reference']['run']['verified_pass'] = False
            assert base.receipt_to_reward(malformed) == (0.0, True, 'verifier_invalid')


@pytest.mark.parametrize('kind', ['good', 'failed', 'incomplete', 'infrastructure'])
def test_reward_rechecks_aggregate_pass_against_execution(semantic_fixture, kind):
    from Reward_GRPO import generalized_cpp_grpo as base
    root = semantic_fixture
    if kind == 'failed':
        (root/'tiny.cpp').write_text('int value(){return 8;}')
    elif kind == 'incomplete':
        (root/'tiny.cpp').write_text('#include <cstdlib>\nint value(){std::_Exit(0);}')
    from Reward_GRPO import global_cpp_verifier_runner as runner
    manifest = dict(schema_version=1, task_id='synthetic-check', fixture_dir=str(root),
        candidate_files=['tiny.h', 'tiny.cpp'], policies={f'G{i:02d}': [] for i in range(1, 6)},
        response_text='\n\n'.join(f'{name}\n```cpp\n{(root/name).read_text()}\n```'
                                    for name in ['tiny.h', 'tiny.cpp']))
    path, output = root.parent/'auth-manifest.json', root.parent/'auth-aggregate'
    path.write_text(json.dumps(manifest))
    runner.main(['--candidate-dir', str(root), '--manifest', str(path),
        '--expected-manifest-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--output-dir', str(output), '--reward-root', str(reward.ROOT/'Reward_GRPO'),
        '--profile', 'live'])
    receipt = json.loads((output/runner.AGGREGATE_RECEIPT).read_text())
    if kind == 'infrastructure':
        policy = next(p for p in receipt['policy_results'] if p['policy_id'] == 'G03')
        policy['kernels'][-1]['facts']['candidate']['run']['infrastructure_error'] = True
    # Derived labels cannot override the runner's underlying execution facts.
    receipt.update(status='pass', score=1.0)
    score, infrastructure, reason = base.receipt_to_reward(receipt)
    assert infrastructure == (kind == 'infrastructure')
    assert (score == 1.0) == (kind == 'good')
    if kind in {'failed', 'incomplete'}:
        assert reason == 'fail' and score <= 0


def test_aggregate_pass_without_execution_is_invalid():
    from Reward_GRPO import generalized_cpp_grpo as base
    assert base.receipt_to_reward({'status': 'pass', 'score': 1.0}) == (
        0.0, True, 'verifier_invalid')


@pytest.mark.parametrize('return_code', [1, 2])
def test_reward_rejects_runner_failure_with_success_receipt(semantic_fixture, tmp_path, monkeypatch, return_code):
    from Reward_GRPO import generalized_cpp_grpo as base
    from Reward_GRPO import global_cpp_verifier_runner as runner
    root = semantic_fixture
    manifest = dict(schema_version=1, task_id='synthetic-check', fixture_dir='fixture',
        candidate_files=['tiny.h', 'tiny.cpp'], policies={f'G{i:02d}': [] for i in range(1, 6)},
        protected_files={str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in root.rglob('*') if path.is_file()
                         and path.name not in {'tiny.h', 'tiny.cpp'}})
    manifest_path = tmp_path/'binding-manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    registry_path = tmp_path/'registry.json'
    registry_path.write_text(json.dumps(dict(schema_version=1, tasks={'synthetic-check': dict(
        manifest='binding-manifest.json', fixture_dir='fixture',
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())})))
    registry = base.TaskRegistry(registry_path)
    original = runner.run
    def inconsistent(args):
        assert original(args) == 0
        return return_code
    monkeypatch.setattr(runner, 'run', inconsistent)
    response = base._render_whole_file_response({name: (root/name).read_text()
                                               for name in ['tiny.h', 'tiny.cpp']})
    record = base.score_sample({'metadata': {'problem_id': 'synthetic-check'},
                                'response': response}, registry)
    assert record['infrastructure_error'] is True
    assert record['reason'] == 'runner_protocol_error'
    assert record['score'] == 0
