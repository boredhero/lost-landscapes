"""Timings cover streamed bodies, errors, and work queued across thread boundaries."""
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from lost_landscapes.utils import request_logging as timing
from lost_landscapes.utils.log_manager import get_request_id, request_id_var, set_request_id


@pytest.mark.asyncio
async def test_stream_completion_and_headers(monkeypatch):
    previous_id = get_request_id()
    events, messages = [], []
    clock = iter([0, 0.1, 0.7])
    monkeypatch.setattr(timing.time, 'perf_counter', lambda: next(clock))
    monkeypatch.setattr(timing.log, 'info', lambda event, **fields: events.append((event, fields, get_request_id())))

    async def app(scope, receive, send):
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'abc', 'more_body': True})
        assert [e[0] for e in events] == ['request_in']
        await send({'type': 'http.response.body', 'body': b'de'})

    async def send(message):
        messages.append(message)

    await timing.RequestLoggingMiddleware(app)({'type': 'http', 'path': '/tiles', 'method': 'GET'}, None, send)
    result = events[-1][1]
    assert result['headers_ms'] == 100
    assert result['elapsed_ms'] == 700
    assert result['response_bytes'] == 5
    assert events[0][2] == events[-1][2] != ''
    assert get_request_id() == previous_id
    assert (b'server-timing', b'app;dur=100.0') in messages[0]['headers']


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [ValueError, asyncio.CancelledError])
async def test_failed_requests_reset_context(monkeypatch, error):
    previous_id = get_request_id()
    events = []
    monkeypatch.setattr(timing.log, 'error', lambda event, **fields: events.append(event))
    async def app(*args):
        raise error()
    with pytest.raises(error):
        await timing.RequestLoggingMiddleware(app)({'type': 'http', 'path': '/fail', 'method': 'GET'}, None, None)
    assert events == ['request_cancelled' if error is asyncio.CancelledError else 'request_failed']
    assert get_request_id() == previous_id


@pytest.mark.asyncio
async def test_executor_preserves_correlation_and_reports_queue(monkeypatch):
    events = []
    monkeypatch.setattr(timing.log, 'info', lambda event, **fields: events.append((event, fields, get_request_id())))
    token = set_request_id('test-rid')
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert await timing.timed_executor(pool, get_request_id) == 'test-rid'
        assert events[0][0] == 'request_work'
        assert events[0][2] == 'test-rid'
        assert events[0][1]['queue_ms'] >= 0
        assert events[0][1]['work_ms'] >= 0
    finally:
        request_id_var.reset(token)
