from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lost_landscapes import visits


def test_daily_counts_deduplicate_reload_and_keep_distinct_tabs(tmp_path):
    path = tmp_path / 'visits.sqlite3'
    browser = uuid4()
    body = visits.Visit(browser_id=browser, visit_id=uuid4())
    assert visits.record_visit(path, body)['added'] is True
    repeated = visits.record_visit(path, body)
    assert (repeated['visits'], repeated['browsers'], repeated['added']) == (1, 1, False)
    second = visits.record_visit(path, visits.Visit(browser_id=browser, visit_id=uuid4()))
    assert (second['visits'], second['browsers']) == (2, 1)
    third = visits.record_visit(path, visits.Visit(browser_id=uuid4(), visit_id=uuid4()))
    assert (third['visits'], third['browsers']) == (3, 2)
    assert str(browser).encode() not in path.read_bytes()


def test_retention_and_daily_rotation(tmp_path):
    path = tmp_path / 'visits.sqlite3'
    now = datetime.now(UTC)
    body = visits.Visit(browser_id=uuid4(), visit_id=uuid4())
    for age in (90, 89, 1, 0):
        visits.record_visit(path, body, now - timedelta(days=age))
    rows = visits.report(path, 90)
    assert len(rows) == 3
    assert all(row['visits'] == row['browsers'] == 1 for row in rows)
    assert len(visits.report(path, 1)) == 1
    assert visits.report(tmp_path / 'missing.sqlite3') == []
    db = visits.connect(path)
    try:
        assert db.execute('SELECT COUNT(DISTINCT browser) FROM visits').fetchone()[0] == 3
    finally:
        db.close()


def test_concurrent_duplicate_delivery(tmp_path):
    path = tmp_path / 'visits.sqlite3'
    body = visits.Visit(browser_id=uuid4(), visit_id=uuid4())
    visits.record_visit(path, body)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: visits.record_visit(path, body), range(8)))
    assert all(row['visits'] == 1 and not row['added'] for row in results)


def test_api_privacy_signals_validation_and_store_outage(tmp_path, monkeypatch):
    monkeypatch.setattr(visits.settings, 'data_dir', tmp_path)
    app = FastAPI()
    app.include_router(visits.router)
    body = {'browser_id': str(uuid4()), 'visit_id': str(uuid4())}
    with TestClient(app) as client:
        for headers in ({'DNT': '1'}, {'Sec-GPC': '1'}):
            assert client.post('/visits', json=body, headers=headers).status_code == 204
        assert not (tmp_path / 'analytics').exists()
        assert client.post('/visits', json={'browser_id': 'invalid'}).status_code == 422
        assert client.post('/visits', json=body).status_code == 204
        def unavailable(*args):
            raise OSError('read only')
        monkeypatch.setattr(visits, 'record_visit', unavailable)
        assert client.post('/visits', json=body).status_code == 503
