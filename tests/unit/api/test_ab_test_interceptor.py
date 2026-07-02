import asyncio
from unittest.mock import MagicMock

from src.audiobook_studio.api.ab_test_interceptor import ABTestAllocator, get_prompt_version


def test_allocator_get_prompt_version():
    allocator = ABTestAllocator()
    # Test that we get a version (either 1 or 2) for a known stage
    version = allocator.get_prompt_version("analyze_structure", book_id="book1", user_id="user1")
    assert version in [1, 2]
    # Test that we get 1 for an unknown stage (should default to 1)
    version = allocator.get_prompt_version("unknown_stage", book_id="book1", user_id="user1")
    assert version == 1


def test_get_prompt_version_dependency():
    # Mock a request with state
    request = MagicMock()
    request.state.ab_test_versions = {"analyze_structure": 2}
    # We have to await the function because it's defined as async
    result = asyncio.run(get_prompt_version(request, "analyze_structure"))
    assert result == 2
    # If not in state, should default to 1
    request.state.ab_test_versions = {}
    result = asyncio.run(get_prompt_version(request, "analyze_structure"))
    assert result == 1
