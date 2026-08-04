"""Shared bounded transport-retry wrapper for provider .generate() calls.

Extracted from harness/agentb.py's own _generate_with_transport_retry, which Track B
has had since its own generation loop was built. Track A's harness/evalmodel.py called
provider.generate() exactly once and folded any failure -- a genuine transient
transport blip (HTTP 429/5xx, a dropped connection, a truncated read) exactly as much
as a hard client error -- into the same generation_error field, indistinguishable from
each other downstream. A transient provider outage during a Track A campaign would
therefore permanently score that (model, task) pair 0, contaminating a capability
metric with pure infrastructure noise. Track B already avoided this by retrying
ProviderRetryableError (see harness/providers/_http.py's retryable/non-retryable
classification) before giving up; this module lets both tracks share that policy
instead of drifting apart.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from harness.providers import GenParams, ProviderAdapter
from harness.providers._http import ProviderRetryableError

DEFAULT_TRANSPORT_RETRY_DELAYS_S = (0.25, 0.5)


def generate_with_transport_retry(
    provider: ProviderAdapter,
    prompt: str,
    system: str,
    params: GenParams,
    *,
    delays_s: tuple[float, ...] = DEFAULT_TRANSPORT_RETRY_DELAYS_S,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Call provider.generate(), retrying ProviderRetryableError up to len(delays_s)
    times with the given delays. Any other exception (including non-retryable
    ProviderHTTPError and SpendCapExceeded) propagates on the first attempt --
    retrying is only ever appropriate for failures the provider itself signals as
    transient."""

    for attempt in range(len(delays_s) + 1):
        try:
            return provider.generate(prompt, system, params)
        except ProviderRetryableError:
            if attempt == len(delays_s):
                raise
            sleep(delays_s[attempt])
    raise AssertionError("transport retry loop did not return or raise")
