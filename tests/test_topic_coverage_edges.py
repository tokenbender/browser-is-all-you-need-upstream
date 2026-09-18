"""Behavioral controls for requirement groups not isolated by the original catalog.

Pytest uses explicit temporary source bindings, not a production registry.
The standalone command requires --registry;
its inputs must be staged explicitly by the caller.
"""
from pathlib import Path
import argparse
import json
from test_topic_coverage import topic_registry  # Explicit pytest-local bindings.
from Reward_GRPO.generalized_cpp_grpo import _registry
from Reward_GRPO.topic_coverage.runner import AuditSession, control_sources, write_json
from Reward_GRPO.topic_coverage.controls import controls, edit


def edge_controls():
    registry = _registry()
    jobs = []
    def add(task, name, files, failed=()):
        jobs.append(dict(task=task, name=name, sources=files, required_failed_groups=failed,
                         expected='fail' if failed else 'pass'))
    task='clock';sources=control_sources(registry.resolve(task),task)
    assert sources['clock.cpp'].count('return *this;') == 2
    add(task,'returns_different_clock', {**sources,'clock.cpp':sources['clock.cpp'].replace(
        'return *this;', 'static clock copy = *this; copy = *this; return copy;')}, ('update_contract',))
    task='complex-numbers';sources=control_sources(registry.resolve(task),task)
    for name,old,new,group in [
        ('add_subtracts_real','Complex sum{re + other.re, im + other.im};','Complex sum{re - other.re, im + other.im};','direct_add'),
        ('subtract_adds_imaginary','Complex diff{re - other.re, im - other.im};','Complex diff{re - other.re, im + other.im};','direct_subtract'),
        ('multiply_wrong_sign','a * c - b * d','a * c + b * d','direct_multiply'),
        ('divide_wrong_real','(a * c + b * d)','(a * c - b * d)','direct_divide')]:
        # The historical reference uses member expressions; the later release
        # uses local a/b/c/d variables. Both controls make the same sign error.
        # edit() still requires exactly one matching anchor and changes it once.
        historical = {
            'a * c - b * d': ('re * other.re - im * other.im',
                              're * other.re + im * other.im'),
            '(a * c + b * d)': ('(re * other.re + im * other.im)',
                                '(re * other.re - im * other.im)'),
        }
        if old in historical and sources['complex_numbers.cpp'].count(old) == 0:
            old, new = historical[old]
        add(task,name,edit(sources,'complex_numbers.cpp',old,new),(group,))
    old='Complex prod{complex.real() * scalar, complex.imag() * scalar};'
    assert sources['complex_numbers.cpp'].count(old)==2
    add(task,'scalar_multiply_adds_imaginary',{**sources,'complex_numbers.cpp':sources['complex_numbers.cpp'].replace(
        old,'Complex prod{complex.real() * scalar, complex.imag() + scalar};')},('scalar_multiply',))
    task='dnd-character';sources=control_sources(registry.resolve(task),task)
    old='std::floor((static_cast<double>(score) - 10) / 2)'
    add(task,'wrong_nonnegative_modifier',edit(sources,'dnd_character.cpp',old,'score >= 10 ? 99 : '+old),('modifier_nonnegative',))
    constant=next(c.sources for c in controls(task,sources) if c.name=='constant_ability_diagnostic')
    add(task,'ability_above_bound',edit(constant,'dnd_character.cpp','return 10;','return 19;'),('ability_range',))
    task='yacht';sources=control_sources(registry.resolve(task),task)
    add(task,'double_face_scores',edit(sources,'yacht.cpp','acc + i : acc','acc + 2 * i : acc'),
        ('ones','twos','threes','fours','fives','sixes'))
    add(task,'choice_drops_one',edit(sources,'yacht.cpp','return total;','return total - 1;'),('choice',))
    add(task,'big_straight_inverted',edit(sources,'yacht.cpp','return dice == big_straight ? 30 : 0;',
        'return dice == big_straight ? 0 : 30;'),('big_straight',))
    task='sublist';sources=control_sources(registry.resolve(task),task)
    add(task,'equal_is_unequal',edit(sources,'sublist.cpp','return List_comparison::equal;',
        'return List_comparison::unequal;'),('equal_relation',))
    # Enum numeric order and wider compatible signed arguments are valid API choices.
    header=sources['sublist.h']
    import re
    match=re.search(r'(enum class List_comparison\s*\{)([^}]+)(\})',header)
    assert match
    reordered=header[:match.start(2)]+' superlist, unequal, equal, sublist '+header[match.end(2):]
    add(task,'reordered_enum_values',{**sources,'sublist.h':reordered})
    task='perfect-numbers';sources=control_sources(registry.resolve(task),task)
    add(task,'wider_signed_parameter',{name:text.replace('classify(int n)','classify(long long n)') for name,text in sources.items()})
    return jobs


def validate(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    entries=[]
    for job in edge_controls():
        with AuditSession(job['task'],output/job['name'],allow_local_execution=True) as session:
            result=session.audit(job['sources'])
        groups={g['group']:g['status'] for g in result.get('candidate',{}).get('groups',[])}
        matched=result['status']==job['expected'] and result.get('candidate',{}).get('build',{}).get('returncode')==0
        matched=matched and all(groups.get(g)=='fail' for g in job['required_failed_groups'])
        entry={k:v for k,v in job.items() if k!='sources'}
        entry.update(status=result['status'],matched=matched)
        entries.append(entry)
        print(json.dumps(entry),flush=True)
    summary=dict(cases=len(entries),matched=sum(e['matched'] for e in entries),entries=entries)
    write_json(output/'summary.json',summary)
    assert all(e['matched'] for e in entries),summary
    return summary


def test_remaining_requirement_groups_and_valid_api_alternatives(tmp_path):
    validate(tmp_path/'edges')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--registry',type=Path,required=True)
    args = parser.parse_args()
    import os
    os.environ['GENERALIZED_CPP_VERIFIER_REGISTRY'] = str(args.registry.resolve())
    AuditSession.__init__.__kwdefaults__['registry_path'] = args.registry.resolve()
    validate(args.output)
