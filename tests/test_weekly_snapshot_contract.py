"""Native weekly writes remain verifiable by the explicit identity migration."""
from datetime import date, timedelta
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / 'runtime/lib', ROOT / 'api'):
    sys.path.insert(0, str(directory))

from migrations.identity_records import verify_records
from status import BackupStatus
from status_api import _load_previous_status_sizes
from weekly_snapshots import read_observations, write_current

JOB = '11111111-1111-4111-8111-111111111111'
RUN = '22222222-2222-4222-8222-222222222222'


def test_native_weekly_sample_supersedes_legacy_and_passes_migration_verifier(tmp_path):
    path = tmp_path / 'weekly.json'
    legacy = BackupStatus(job_id=JOB, identity_state="assigned", timestamp='2026-09-06 12:00:00', repository_size=100,
                          repository_snapshot='/fixture/repo')
    legacy.source_path = tmp_path / 'legacy.status'
    write_current(path, {JOB: legacy})
    native = BackupStatus(job_id=JOB, identity_state="assigned", run_id=RUN, timestamp='2026-09-01 12:00:00', repository_size=120,
                          repository_key_snapshot='repo', repository_snapshot='/fixture/repo')
    native.source_path = tmp_path / 'native.status'
    write_current(path, {JOB: native})
    before = path.read_bytes()
    rows = read_observations(path)
    assert len(rows) == 1 and rows[0]['size'] == 120 and rows[0]['run_id'] == RUN
    assert not verify_records({str(path): {'kind': 'weekly', 'data': json.loads(before)}},
                              {JOB: {'job_id': JOB, 'repository_key': 'repo'}}, {})
    write_current(path, {JOB: legacy})
    assert path.read_bytes() == before


@pytest.mark.parametrize('mutate', [
    lambda data: data.update(schema_version=2),
    lambda data: data['observations'][0].update(source_records=[{}]),
    lambda data: data['observations'][0].update(job_id='legacy_name'),
])
def test_invalid_snapshot_is_rejected_without_rewrite(tmp_path, mutate):
    path = tmp_path / 'weekly.json'
    week = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    data = {'schema_version': 1, 'identity_schema_version': 1, 'observations': [
        {'job_id': JOB, 'week': week, 'size': 100, 'source_records': [{'source': '/fixture/old', 'locator': ''}]}]}
    mutate(data)
    path.write_text(json.dumps(data)); before = path.read_bytes()
    with pytest.raises(ValueError):
        write_current(path, {})
    assert path.read_bytes() == before


def test_future_legacy_size_is_not_a_native_run_growth_baseline():
    legacy = BackupStatus(job_id=JOB, identity_state="assigned", timestamp='2026-09-06 12:00:00', repository_size=100, repository_snapshot='/fixture/repo')
    native = BackupStatus(job_id=JOB, identity_state="assigned", run_id=RUN, timestamp='2026-09-01 12:00:00', repository_size=120, repository_snapshot='/fixture/repo')
    assert _load_previous_status_sizes([legacy, native], {JOB: native}) == {}
