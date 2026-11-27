"""Suite-wide guards so a hung test can never stall the pipeline again.

1. Hard per-test deadline (default 30 s, override with TEST_TIMEOUT). Uses SIGALRM, so it
   needs no plugin and fails the test with a clear message instead of hanging forever
   (catches infinite loops and network waits alike).
2. Tests run offline: SEO_OFFLINE=1 makes live lookups return instantly; nothing in
   the suite depends on internet access.
"""
import os, signal, sys
import pytest

os.environ.setdefault("SEO_OFFLINE", "1")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))

LIMIT = int(os.environ.get("TEST_TIMEOUT", "30"))


def pytest_configure(config):
    config.addinivalue_line("markers", "budget(seconds): longer hang-guard limit for heavy end-to-end tests")


@pytest.fixture(autouse=True)
def _deadline(request):
    m = request.node.get_closest_marker("budget")
    limit = int(m.args[0]) if m else LIMIT
    if not hasattr(signal, "SIGALRM") or LIMIT <= 0:
        yield; return
    def boom(*_):
        raise TimeoutError(f"{request.node.nodeid} exceeded {limit}s (hang guard in tests/conftest.py)")
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(limit)
    try:
        yield
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, old)
