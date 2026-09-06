"""#475: union retention compared against the shipped Borg 1.4 implementation."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from lib.retention import Archive, parse_archives, plan_retention, prune_union

POLICY = {'daily': 1, 'weekly': 1, 'monthly': 0, 'yearly': 0}


def archive(name, date, number):
    return Archive(name, f'{number:064x}', datetime.fromisoformat(date).replace(tzinfo=timezone.utc))


def test_one_policy_for_current_and_historical_prefixes_with_foreign_archives():
    rows = [archive('new-1', '2026-09-06T12:00:00', 1), archive('old-2', '2026-09-06T11:00:00', 2),
            archive('old-3', '2026-08-25T12:00:00', 3), archive('new-4', '2026-08-24T12:00:00', 4),
            archive('unrelated-5', '2026-09-07T12:00:00', 5), archive('older-6', '2026-08-01T12:00:00', 6)]
    keep, discard = plan_retention(rows, ['new', 'old'], POLICY)
    assert {a.name for a in keep} == {'new-1', 'old-3'}
    assert {a.name for a in discard} == {'old-2', 'new-4'}
    assert plan_retention(rows, ['old','new'], POLICY) == (keep, discard)


def test_checkpoint_and_oldest_fallback_match_borg_rules():
    rows = [archive('p-1.checkpoint', '2026-09-06T12:00:00', 1), archive('p-2', '2026-09-06T11:00:00', 2),
            archive('p-3.checkpoint.1', '2026-09-06T10:30:00', 3), archive('p-4', '2026-09-06T10:00:00', 4)]
    keep, discard = plan_retention(rows, ['p'], {'daily': 7,'weekly':0,'monthly':0,'yearly':0})
    assert {a.name for a in keep} == {'p-1.checkpoint','p-2','p-4'}
    assert [a.name for a in discard] == ['p-3.checkpoint.1']


@pytest.mark.parametrize('prefixes,policy', [([], POLICY), (['*'],POLICY), (['x','x'],POLICY), (['x'],dict.fromkeys(POLICY,0)), (['x'],{**POLICY,'daily':-1})])
def test_invalid_scope_never_starts_borg(monkeypatch, prefixes, policy):
    monkeypatch.setattr('lib.retention.subprocess.Popen', lambda *a,**k: pytest.fail('Borg must not start'))
    with pytest.raises(ValueError):
        prune_union('/synthetic/repo', prefixes, policy)


def inventory(rows):
    return {'archives':[{'name':a.name, 'id':a.id, 'time':a.timestamp.isoformat()} for a in rows]}


def mock_lists(monkeypatch, outputs):
    class Process:
        def __init__(self):
            self.returncode, self.output = outputs.pop(0)
        def communicate(self): return self.output, None
    monkeypatch.setattr('lib.retention.subprocess.Popen', lambda *a, **k: Process())


@pytest.mark.parametrize('change', ['id','name','added','failed'])
def test_changed_or_failed_inventory_never_deletes(monkeypatch, change):
    rows = [archive('new-1','2026-09-06T12:00:00',1), archive('old-2','2026-09-06T11:00:00',2)]
    second = inventory(rows)
    if change == 'id': second['archives'][1]['id'] = 'f' * 64
    if change == 'name': second['archives'][1]['name'] = 'foreign-renamed'
    if change == 'added': second['archives'].append({'name':'old-3','id':'d'*64,'time':'2026-09-06T12:30:00'})
    mock_lists(monkeypatch, [(0,json.dumps(inventory(rows))), (2 if change == 'failed' else 0,json.dumps(second))])
    monkeypatch.setattr('lib.borg_runner._run_borg', lambda *a,**k: pytest.fail('No deletion after changed inventory'))
    with pytest.raises(ValueError):
        prune_union('/synthetic/repo', ['new','old'], {'daily':1,'weekly':0,'monthly':0,'yearly':0})


def test_no_candidates_never_issues_repository_delete(monkeypatch):
    mock_lists(monkeypatch, [(0,'{"archives":[]}')])
    monkeypatch.setattr('lib.borg_runner._run_borg', lambda *a,**k: pytest.fail('Never delete the repository'))
    assert prune_union('/synthetic/repo', ['owned'], POLICY) == 0


def test_exact_names_use_one_command_with_option_terminator(monkeypatch):
    rows = [archive('new-1','2026-09-06T12:00:00',1), archive('old-2','2026-09-06T11:00:00',2), archive('old-3','2026-09-06T10:00:00',3)]
    output = json.dumps(inventory(rows))
    mock_lists(monkeypatch, [(0,output),(0,output)])
    commands=[]
    monkeypatch.setattr('lib.borg_runner._run_borg', lambda cmd, *a: commands.append(cmd) or 0)
    assert prune_union('/synthetic/repo', ['new','old'], {'daily':1,'weekly':0,'monthly':0,'yearly':0}) == 0
    assert len(commands)==1
    assert commands[0][-4:] == ['--','/synthetic/repo','old-2','old-3']


def test_shipped_borg_union_policy_and_deletion(tmp_path, monkeypatch):
    binary = ROOT / 'runtime/bin/borg/borg-linux-glibc231-x86_64-1.4.5'
    if not binary.is_file(): pytest.skip('Shipped Borg binary unavailable')
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    (bin_dir / 'borg').symlink_to(binary)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    for key in ('BORG_CACHE_DIR','BORG_SECURITY_DIR','BORG_KEYS_DIR'):
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    monkeypatch.delenv('BORG_REPO', raising=False)
    monkeypatch.delenv('BORG_PASSCOMMAND', raising=False)
    monkeypatch.setenv('TZ', 'UTC')
    repo = tmp_path / 'repo'
    source = tmp_path / 'source'; source.mkdir(); (source / 'file').write_text('synthetic retention test')
    def borg(*args):
        result = subprocess.run(['borg',*args],capture_output=True,text=True,timeout=45,cwd=source)
        assert result.returncode == 0, result.stderr
        return result
    borg('init','--encryption=none',str(repo))
    dates = ['2026-09-06T12:00:00','2026-09-06T11:00:00','2026-09-01T11:00:00','2026-08-25T11:00:00',
             '2026-08-24T11:00:00','2026-07-20T11:00:00','2025-12-30T11:00:00','2024-12-29T11:00:00']
    names=[]
    for i,date in enumerate(dates):
        name=f'managed-{chr(97+i%2)}-{i}'
        names.append(name)
        borg('create','--timestamp',date,str(repo)+'::'+name,'file')
    borg('create','--timestamp','2026-09-07T12:00:00',str(repo)+'::foreign-newest','file')
    rows = parse_archives(json.loads(borg('list','--json','--consider-checkpoints',str(repo)).stdout))
    policy={'daily':1,'weekly':1,'monthly':1,'yearly':1}
    keep, discard = plan_retention(rows,['managed-a','managed-b'],policy)
    dry = borg('prune','--dry-run','--list','--glob-archives','managed-*','--keep-daily','1','--keep-weekly','1','--keep-monthly','1','--keep-yearly','1',str(repo))
    expected={name for name in names if any('Would prune:' in line and name in line for line in dry.stderr.splitlines())}
    assert expected and {a.name for a in discard} == expected, dry.stderr
    assert prune_union(str(repo),['managed-a','managed-b'],policy) == 0
    remaining = json.loads(borg('list','--json',str(repo)).stdout)['archives']
    assert {r['name'] for r in remaining} == {a.name for a in keep} | {'foreign-newest'}
    borg('check',str(repo))


def test_equal_timestamps_preserve_borg_reverse_inventory_order():
    rows = [archive('managed-a', '2026-10-25T01:30:00', 1),
            archive('managed-z', '2026-10-25T01:30:00', 2),
            archive('managed-z.checkpoint', '2026-10-25T01:30:00', 3)]
    keep, discard = plan_retention(rows, ['managed'], {'daily': 1, 'weekly': 0, 'monthly': 0, 'yearly': 0})
    assert [a.name for a in keep] == ['managed-z.checkpoint', 'managed-z']
    assert [a.name for a in discard] == ['managed-a']


def test_shipped_borg_ties_local_midnight_and_dst_fold(tmp_path, monkeypatch):
    """Use native prune as the oracle for local calendar buckets and tied times."""
    import re
    import time

    binary = ROOT / 'runtime/bin/borg/borg-linux-glibc231-x86_64-1.4.5'
    if not binary.is_file():
        pytest.skip('Shipped Borg binary unavailable')
    if not hasattr(time, 'tzset'):
        pytest.skip('Local timezone switching unavailable')
    previous_tz = os.environ.get('TZ')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'borg').symlink_to(binary)
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])
    for key in tuple(os.environ):
        if key.startswith('BORG_'):
            monkeypatch.delenv(key)
    for key in ('BORG_BASE_DIR', 'BORG_CACHE_DIR', 'BORG_SECURITY_DIR', 'BORG_KEYS_DIR'):
        monkeypatch.setenv(key, str(tmp_path / key.lower()))
    monkeypatch.setenv('TZ', 'Europe/Berlin')
    time.tzset()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'file').write_text('synthetic calendar retention test')
    repo = tmp_path / 'repo'

    def borg(*args, utc_inventory=False):
        env = dict(os.environ)
        if utc_inventory:
            env['TZ'] = 'UTC'
        result = subprocess.run(['borg', *args], capture_output=True, text=True,
                                timeout=45, cwd=source, env=env)
        assert result.returncode == 0, result.stderr
        return result

    try:
        borg('init', '--encryption=none', str(repo))
        dates = {
            'managed-old': '2026-10-23T21:30:00+00:00',
            'managed-before': '2026-10-24T21:30:00+00:00',
            'managed-fold-early': '2026-10-25T00:30:00+00:00',
            'managed-tie-a': '2026-10-25T01:30:00+00:00',
            'managed-tie-z': '2026-10-25T01:30:00+00:00',
            'managed-z.checkpoint': '2026-10-25T01:30:00+00:00',
        }
        for name, timestamp in dates.items():
            borg('create', '--timestamp', timestamp, str(repo) + '::' + name, 'file')
        local_inventory = json.loads(borg('list', '--json', '--consider-checkpoints', str(repo)).stdout)
        local_times = {a['name']: a['time'] for a in local_inventory['archives']}
        # Borg JSON has local naive times: both sides of the DST fold look equal.
        assert local_times['managed-before'] == '2026-10-24T23:30:00.000000'
        assert local_times['managed-fold-early'] == local_times['managed-tie-z'] == '2026-10-25T02:30:00.000000'
        utc_inventory = json.loads(borg('list', '--json', '--consider-checkpoints', str(repo),
                                        utc_inventory=True).stdout)
        rows = parse_archives(utc_inventory)
        commands = []
        monkeypatch.setattr('lib.borg_runner._run_borg', lambda cmd, *args: commands.append(cmd) or 0)

        for daily, expected_names in (
                (1, {'managed-tie-z', 'managed-z.checkpoint'}),
                (2, {'managed-tie-z', 'managed-before', 'managed-z.checkpoint'})):
            policy = {'daily': daily, 'weekly': 0, 'monthly': 0, 'yearly': 0}
            dry = borg('prune', '--dry-run', '--list', '--glob-archives', 'managed-*',
                       '--keep-daily', str(daily), str(repo))
            pruned_ids = {re.search(r'\[([0-9a-f]{64})\]', line).group(1)
                          for line in dry.stderr.splitlines() if line.startswith('Would prune:')}
            oracle_keep = {a.name for a in rows if a.id not in pruned_ids}
            oracle_discard = {a.name for a in rows if a.id in pruned_ids}
            assert oracle_keep == expected_names, dry.stderr
            keep, discard = plan_retention(rows, ['managed'], policy)
            assert {a.name for a in keep} == oracle_keep, dry.stderr
            assert {a.name for a in discard} == oracle_discard, dry.stderr
            commands.clear()
            assert prune_union(str(repo), ['managed'], policy) == 0
            assert len(commands) == 1
            archive_args = commands[0][commands[0].index('--') + 2:]
            assert set(archive_args) == oracle_discard, dry.stderr
            assert os.environ['TZ'] == 'Europe/Berlin'
        # Both inventory reads are real; only the final deletion was intercepted.
        unchanged = json.loads(borg('list', '--json', '--consider-checkpoints', str(repo),
                                    utc_inventory=True).stdout)
        assert unchanged['archives'] == utc_inventory['archives']
    finally:
        if previous_tz is None:
            monkeypatch.delenv('TZ', raising=False)
        else:
            monkeypatch.setenv('TZ', previous_tz)
        time.tzset()
