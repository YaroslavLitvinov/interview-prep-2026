"""Local pytest config for the dimensions framework's own tests."""

import pytest_asyncio  # noqa: F401  (ensures plugin loaded)

# Tell pytest-asyncio to treat every `async def test_*` here as a coroutine
# without requiring per-test @pytest.mark.asyncio. Each test in this dir is
# async, so auto mode is the right default.
collect_ignore: list[str] = []


def pytest_collection_modifyitems(config, items):
    import pytest
    for item in items:
        if "asyncio" in item.keywords:
            continue
        if hasattr(item, "function") and getattr(item.function, "_is_coroutine", False):
            item.add_marker(pytest.mark.asyncio)
