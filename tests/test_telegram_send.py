# -*- coding: utf-8 -*-
"""Отправка в Telegram: 429 не должен приводить к потере вакансии."""
import utils


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.ok = status_code == 200
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def patch_post(monkeypatch, responses):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr(utils.requests, "post", fake_post)
    monkeypatch.setattr(utils.time, "sleep", lambda _s: None)
    return calls


def test_successful_send_returns_true(monkeypatch):
    patch_post(monkeypatch, [FakeResponse(200)])
    assert utils.send_telegram("t", "c", "привет") is True


def test_rate_limit_is_retried_and_succeeds(monkeypatch):
    responses = [
        FakeResponse(429, {"parameters": {"retry_after": 3}}),
        FakeResponse(200),
    ]
    calls = patch_post(monkeypatch, responses)
    assert utils.send_telegram("t", "c", "привет") is True
    assert len(calls) == 2


def test_rate_limit_waits_the_requested_time(monkeypatch):
    slept = []
    monkeypatch.setattr(utils.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(utils.requests, "post",
                        lambda url, json=None, timeout=None: FakeResponse(429, {"parameters": {"retry_after": 7}}))
    assert utils.send_telegram("t", "c", "привет") is False
    assert slept and slept[0] >= 7


def test_permanent_error_returns_false_without_retry_storm(monkeypatch):
    calls = patch_post(monkeypatch, [FakeResponse(400, {"description": "bad html"})])
    assert utils.send_telegram("t", "c", "привет") is False
    assert len(calls) == 1


def test_network_error_returns_false(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise OSError("сеть моргнула")

    monkeypatch.setattr(utils.requests, "post", boom)
    monkeypatch.setattr(utils.time, "sleep", lambda _s: None)
    assert utils.send_telegram("t", "c", "привет") is False
