"""HTTP requests to the paper sources, with retries for failures that waiting can fix."""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from collections.abc import Callable

logger = logging.getLogger("journal_club")

USER_AGENT = "journal-club-paper-digest"
#: HTTP statuses worth retrying: rate limiting and server-side failures.
TRANSIENT_HTTP = frozenset({429, 500, 502, 503, 504})
#: The wait after the first failure; it doubles on each further retry.
RETRY_BACKOFF_S = 10.0
#: The longest a server's ``Retry-After`` is honoured for. A source that asks for longer is treated as down,
#: so the digest moves on to the fallback source instead of sitting out the job's timeout.
MAX_RETRY_AFTER_S = 60.0


class FetchError(RuntimeError):
    """A paper source could not deliver a complete answer."""


def http_get(url: str) -> str:
    """Return the body of a GET request to *url*.

    Args:
        url: The URL.

    Returns:
        The response body, decoded as UTF-8.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 -- fixed https URLs
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return response.read().decode("utf-8")


def backoff_s(retry: int) -> float:
    """Return the wait before retry number *retry*, counting from 0.

    Args:
        retry: Which retry this is.

    Returns:
        :data:`RETRY_BACKOFF_S`, doubled *retry* times.
    """
    return RETRY_BACKOFF_S * 2**retry


def retry_after_s(error: urllib.error.HTTPError) -> float | None:
    """Return the wait a response's ``Retry-After`` header asks for, in seconds.

    Args:
        error: The error response.

    Returns:
        The wait, or None if there is no header or it is in the HTTP-date form, which is not used by the
        sources queried here.
    """
    value = error.headers.get("Retry-After") if error.headers is not None else None
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def get_with_retries(url: str, *, get: Callable[[str], str], sleep: Callable[[float], None], retries: int) -> str:
    """Return ``get(url)``, retrying rate limiting, server errors and network failures.

    Waits follow :func:`backoff_s`, lengthened to the server's ``Retry-After`` when it asks for more, up to
    :data:`MAX_RETRY_AFTER_S`.

    Args:
        url: The URL.
        get: Fetches a URL and returns the body.
        sleep: Waits the given number of seconds.
        retries: How many times to retry before giving up.

    Returns:
        The response body.

    Raises:
        urllib.error.HTTPError: If the status is not transient, or still fails after *retries* retries.
        urllib.error.URLError: If the network still fails after *retries* retries.
        TimeoutError: If the request still times out after *retries* retries.
    """
    for retry in range(retries + 1):
        try:
            return get(url)
        except urllib.error.HTTPError as error:
            if error.code not in TRANSIENT_HTTP or retry == retries:
                raise
            wait = backoff_s(retry)
            asked = retry_after_s(error)
            if asked is not None:
                wait = max(wait, min(asked, MAX_RETRY_AFTER_S))
            logger.warning("HTTP %d from %s; retrying in %.0f s", error.code, url.split("?", 1)[0], wait)
        except (urllib.error.URLError, TimeoutError) as error:
            if retry == retries:
                raise
            wait = backoff_s(retry)
            logger.warning("Request to %s failed (%s); retrying in %.0f s", url.split("?", 1)[0], error, wait)
        sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover -- the last iteration returns or raises
