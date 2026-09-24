"""Fails the run if any test wrote into docs/ or data/. Runs last (see conftest.pytest_collection_modifyitems)."""
from tests.conftest import _snapshot


def test_docs_and_data_untouched(request):
    before = request.config._output_snapshot
    after = _snapshot()
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    assert not changed, "tests wrote into docs/ or data/: " + ", ".join(changed[:20])
