"""Compile topic controls without requiring an external task registry."""
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from Reward_GRPO import generalized_cpp_grpo as reward
from Reward_GRPO.topic_coverage.controls import controls, sublist_enum_controls
from Reward_GRPO.topic_coverage.runner import AuditSession
from Reward_GRPO.topic_coverage.specs import TOPICS

ROOT = Path(__file__).resolve().parents[1]
# Control template from the maintained ba1380e Sublist reference.
SUBLIST_SOURCES = {
    "sublist.h": """#pragma once

#include <vector>

namespace sublist {
    enum class List_comparison { equal, sublist, superlist, unequal };

    List_comparison sublist(const std::vector<int>& list_one, const std::vector<int>& list_two);
}  // namespace sublist
""",
    "sublist.cpp": """#include "sublist.h"

#include <algorithm>
#include <iterator>

namespace sublist {
bool is_sublist(const std::vector<int>& sublist,
                const std::vector<int>& superlist) {
    auto superlist_end = std::prev(
        superlist.end(), std::max<std::size_t>(1, sublist.size()) - 1);
    for (auto it{superlist.begin()}; it != superlist_end; std::advance(it, 1)) {
        if (std::equal(sublist.begin(), sublist.end(), it)) return true;
    }
    return false;
}

List_comparison sublist(const std::vector<int>& list_one,
                        const std::vector<int>& list_two) {
    if (list_one == list_two) {
        return List_comparison::equal;
    }
    if (list_one.size() < list_two.size() && is_sublist(list_one, list_two)) {
        return List_comparison::sublist;
    }
    if (list_one.size() > list_two.size() && is_sublist(list_two, list_one)) {
        return List_comparison::superlist;
    }
    return List_comparison::unequal;
}
}  // namespace sublist
""",
}
PERFECT_SOURCES = {name: (ROOT/'Reward_GRPO/topic_coverage/references/perfect-numbers'/name).read_text()
                   for name in ['perfect_numbers.h', 'perfect_numbers.cpp']}
PERFECT_CONTROLS = controls('perfect-numbers', PERFECT_SOURCES)


def execute(task, sources, tmp_path):
    session = AuditSession.__new__(AuditSession)
    session.task_id, session.topic = task, TOPICS[task]
    session.work, session.output = tmp_path/'work', tmp_path/'output'
    session.work.mkdir()
    session.output.mkdir()
    session.compiler, session.compile_timeout, session.run_timeout = shutil.which('g++'), 90, 30
    assert session.compiler, 'g++ is required for topic control regressions'
    session.groups, session.repeats = session.topic.groups, 2
    session.binding = SimpleNamespace(manifest={'candidate_files': list(sources)})
    return session._execute(sources, 'candidate')


@pytest.mark.parametrize('control', PERFECT_CONTROLS, ids=lambda control: control.name)
def test_perfect_numbers_control_outcomes(control, tmp_path):
    assert control.sources != PERFECT_SOURCES, 'control must change its source'
    result = execute('perfect-numbers', control.sources, tmp_path)
    assert result['status'] == control.expected
    if control.kind in {'positive', 'semantic'}:
        assert result['build']['returncode'] == 0
        assert result['reason'] == 'topic_checks'
    if control.expected == 'pass':
        assert all(group['status'] == 'pass' for group in result['groups'])
    elif control.required_failed_group:
        failed = next(group for group in result['groups']
                      if group['group'] == control.required_failed_group)
        assert failed['status'] == 'fail'


def test_perfect_numbers_reference_and_registry_independence(tmp_path, monkeypatch):
    def unavailable():
        raise AssertionError('topic controls must not read the mutable registry')
    monkeypatch.setattr(reward, '_registry', unavailable)
    current = controls('perfect-numbers', PERFECT_SOURCES)
    assert {control.name: control.sources for control in current} == {
        control.name: control.sources for control in PERFECT_CONTROLS}
    result = execute('perfect-numbers', PERFECT_SOURCES, tmp_path)
    assert result['status'] == 'pass' and result['build']['returncode'] == 0


@pytest.mark.parametrize('control', sublist_enum_controls(SUBLIST_SOURCES), ids=lambda control: control.name)
def test_sublist_enum_control_outcomes(control, tmp_path):
    assert control.sources != SUBLIST_SOURCES
    result = execute('sublist', control.sources, tmp_path)
    assert result['build']['returncode'] == 0
    assert result['status'] == control.expected and result['reason'] == 'topic_checks'
    assert len(result['groups']) == len(TOPICS['sublist'].groups)
    assert all(group['status'] == control.expected for group in result['groups'])
    if control.expected == 'pass':
        records = {group['group']: group for group in result['groups']}
        checks = sum(records[group]['runs'][0]['checks'] for group in TOPICS['sublist'].groups[:4])
        assert checks >= 115600 * 3
        assert records['empty_lists']['runs'][0]['checks'] >= 681 * 3
    else:
        assert all(group['runs'][0]['requirement'] == 'named relations are distinct'
                   for group in result['groups'])
