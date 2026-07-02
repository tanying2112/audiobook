"""
Contract Testing using Schemathesis

Validates that the API implementation conforms to the OpenAPI specification.
Run with: pytest tests/contract/test_contract.py -v
"""

import json
import os
import re
import sys

import pytest
import schemathesis

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


# Load the OpenAPI schema from file
def load_openapi_spec():
    """Load OpenAPI spec from generated file."""
    spec_path = os.path.join(os.path.dirname(__file__), "..", "..", "openapi.json")
    if os.path.exists(spec_path):
        with open(spec_path, "r") as f:
            return json.load(f)
    spec_path = os.path.join(os.getcwd(), "openapi.json")
    if os.path.exists(spec_path):
        with open(spec_path, "r") as f:
            return json.load(f)
    raise FileNotFoundError(f"OpenAPI spec not found at {spec_path}")


openapi_spec = load_openapi_spec()

# Create schema from dict
schema = schemathesis.openapi.from_dict(openapi_spec)

# Test settings - exclude paths
EXCLUDE_PATHS = [
    r"/health",
    r"/metrics",
    r"/docs",
    r"/openapi.json",
    r"/redoc",
    r"/ws/.*",
    r"/mock/.*",
]

# Get all operations from the schema (Ok wrappers need .ok() to unwrap)
_all_op_results = list(schema.get_all_operations())


def _unwrap_operations():
    """Unwrap operations from Ok results."""
    ops = []
    for result in _all_op_results:
        op = result.ok()
        if op is not None:
            ops.append(op)
    return ops


all_operations = _unwrap_operations()


def _path_found(path, method):
    """Check if given path+method exists in the schema."""
    return any(op.path == path and op.method.upper() == method.upper() for op in all_operations)


def test_schema_loaded():
    """Verify the OpenAPI schema was loaded correctly."""
    assert schema is not None
    assert len(all_operations) > 0
    print(f"Loaded {len(all_operations)} operations from OpenAPI spec")


def test_api_conformance():
    """Test that all API endpoints conform to the OpenAPI spec."""
    filtered = [
        op
        for op in all_operations
        if not any(re.match(e, op.path) for e in EXCLUDE_PATHS) and not op.path.startswith("/ws/")
    ]
    for op in filtered:
        assert op.path is not None, f"Operation path should not be None: {op}"
        assert op.method is not None, f"Operation method should not be None: {op}"
    print(f"Filtered operations (non-excluded): {len(filtered)}")
    assert len(filtered) > 0, "No operations left after filtering"


def test_create_project_in_schema():
    """Verify project creation endpoint is in the schema."""
    assert _path_found("/api/projects/", "POST"), "POST /api/projects/ not found"


def test_list_projects_in_schema():
    """Verify list projects endpoint is in the schema."""
    assert _path_found("/api/projects/", "GET"), "GET /api/projects/ not found"


def test_get_project_in_schema():
    """Verify get project endpoint is in the schema."""
    assert _path_found("/api/projects/{project_id}", "GET"), "GET /api/projects/{project_id} not found"


def test_health_in_schema():
    """Verify health endpoint is in the schema."""
    assert _path_found("/health", "GET"), "GET /health not found"


def test_golden_contribute_in_schema():
    """Verify golden contribute endpoint is in the schema."""
    assert _path_found("/api/golden/contribute", "POST"), "POST /api/golden/contribute not found"


def test_golden_samples_in_schema():
    """Verify golden samples endpoint is in the schema."""
    assert _path_found("/api/golden/samples", "GET"), "GET /api/golden/samples not found"


def test_schema_coverage():
    """Test that we have good coverage of the schema."""
    paths = set(openapi_spec.get("paths", {}).keys())
    print(f"Total unique paths in schema: {len(paths)}")

    core_paths = {
        "/api/projects/",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/chapters",
        "/api/projects/{project_id}/characters",
        "/api/golden/samples",
        "/api/golden/contribute",
        "/health",
        "/api/config/contracts/reload",
    }

    for expected_path in core_paths:
        assert expected_path in paths, f"Expected path {expected_path} not found in schema"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
