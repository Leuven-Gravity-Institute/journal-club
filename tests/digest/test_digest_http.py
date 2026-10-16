"""Requests to the paper sources: what is retried, how long it waits, and what surfaces."""

from __future__ import annotations

import io
import urllib.error
import urllib.request

import pytest
from builders import http_error, scripted_get

from journal_club.digest.http import (
    MAX_RETRY_AFTER_S,
    RETRY_BACKOFF_S,
    TRANSIENT_HTTP,
    backoff_s,
    get_with_retries,
    http_get,
    retry_after_s,
)

pytestmark = pytest.mark.unit

URL = "https://example.org/api?q=x"


class TestHttpGet:
    """The real request."""

    def test_the_request_identifies_itself_and_decodes_utf8(self, monkeypatch) -> None:
        """ArXiv and INSPIRE both ask API clients to send a descriptive User-Agent."""
        seen = {}

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout):
            seen["agent"] = request.get_header("User-agent")
            seen["timeout"] = timeout
            return Response("Ünïcode".encode())

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        assert http_get(URL) == "Ünïcode"
        assert seen == {"agent": "journal-club-paper-digest", "timeout": 60}


class TestRetryAfter:
    """Reading the server's ``Retry-After``."""

    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("120", 120.0),
            ("2.5", 2.5),
            ("0", 0.0),
            ("-5", 0.0),
            ("Wed, 21 Oct 2026 07:28:00 GMT", None),
            ("soon", None),
            (None, None),
        ],
    )
    def test_seconds_are_read_and_anything_else_is_ignored(self, header: str | None, expected) -> None:
        """Only the delay-seconds form is used; an unreadable header falls back to the backoff."""
        assert retry_after_s(http_error(429, header)) == expected

    def test_an_error_without_headers_has_no_retry_after(self) -> None:
        """``urllib`` can raise an HTTPError with no headers at all."""
        assert retry_after_s(urllib.error.HTTPError(URL, 503, "error", None, None)) is None  # type: ignore[arg-type]


class TestGetWithRetries:
    """The retry loop."""

    def test_a_success_is_returned_without_waiting(self) -> None:
        """No sleep on the happy path."""
        get, _ = scripted_get("body")
        waits: list[float] = []
        assert get_with_retries(URL, get=get, sleep=waits.append, retries=3) == "body"
        assert waits == []

    @pytest.mark.parametrize("code", sorted(TRANSIENT_HTTP))
    def test_transient_http_errors_are_retried(self, code: int) -> None:
        """Rate limiting and server errors pass; the next attempt usually succeeds."""
        get, _ = scripted_get(http_error(code), "body")
        assert get_with_retries(URL, get=get, sleep=lambda _: None, retries=3) == "body"

    @pytest.mark.parametrize("failure", [urllib.error.URLError("reset"), TimeoutError()])
    def test_network_failures_are_retried(self, failure: Exception) -> None:
        """A dropped connection or a timeout is as transient as a 503."""
        get, _ = scripted_get(failure, "body")
        assert get_with_retries(URL, get=get, sleep=lambda _: None, retries=3) == "body"

    def test_the_wait_doubles_between_retries(self) -> None:
        """Backing off exponentially is what gets a rate-limited client unblocked."""
        get, _ = scripted_get(http_error(429), urllib.error.URLError("x"), http_error(503), "body")
        waits: list[float] = []
        get_with_retries(URL, get=get, sleep=waits.append, retries=3)
        assert waits == [RETRY_BACKOFF_S, 2 * RETRY_BACKOFF_S, 4 * RETRY_BACKOFF_S]
        assert waits == [backoff_s(0), backoff_s(1), backoff_s(2)]

    def test_a_longer_retry_after_is_honoured(self) -> None:
        """When the server asks for more than the backoff, it gets it."""
        get, _ = scripted_get(http_error(429, "45"), "body")
        waits: list[float] = []
        get_with_retries(URL, get=get, sleep=waits.append, retries=3)
        assert waits == [45.0]

    def test_a_shorter_retry_after_does_not_shorten_the_backoff(self) -> None:
        """The backoff is a floor: a server saying "1" would otherwise be hammered."""
        get, _ = scripted_get(http_error(429, "1"), "body")
        waits: list[float] = []
        get_with_retries(URL, get=get, sleep=waits.append, retries=3)
        assert waits == [RETRY_BACKOFF_S]

    def test_a_very_long_retry_after_is_capped(self) -> None:
        """A source that asks for an hour is treated as down, so the fallback is reached in time."""
        get, _ = scripted_get(http_error(429, "3600"), "body")
        waits: list[float] = []
        get_with_retries(URL, get=get, sleep=waits.append, retries=3)
        assert waits == [MAX_RETRY_AFTER_S]

    def test_rate_limiting_that_persists_surfaces(self) -> None:
        """Retries are bounded: once they are spent, the last error is raised."""
        get, urls = scripted_get(*[http_error(429)] * 3)
        with pytest.raises(urllib.error.HTTPError) as raised:
            get_with_retries(URL, get=get, sleep=lambda _: None, retries=2)
        assert raised.value.code == 429
        assert len(urls) == 3

    @pytest.mark.parametrize("failure", [urllib.error.URLError("down"), TimeoutError()])
    def test_a_network_failure_that_persists_surfaces(self, failure: Exception) -> None:
        """The same bound applies to network failures."""
        get, urls = scripted_get(*[failure] * 2)
        with pytest.raises(type(failure)):
            get_with_retries(URL, get=get, sleep=lambda _: None, retries=1)
        assert len(urls) == 2

    @pytest.mark.parametrize("code", [400, 403, 404])
    def test_a_client_error_is_not_retried(self, code: int) -> None:
        """A 4xx other than 429 means the request is wrong; retrying it only delays the failure."""
        get, urls = scripted_get(http_error(code))
        with pytest.raises(urllib.error.HTTPError):
            get_with_retries(URL, get=get, sleep=lambda _: None, retries=3)
        assert len(urls) == 1
