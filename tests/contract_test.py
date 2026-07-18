"""
Contract Testing using Schemathesis - Quick validation test
"""

import json
import os

import pytest
import schemathesis

# This test requires a generated OpenAPI spec at /tmp/openapi.json
# Skip if not available (e.g., in CI without API generation step)
OPENAPI_PATH = "/tmp/openapi.json"

@pytest.mark.skipif(not os.path.exists(OPENAPI_PATH), reason="OpenAPI spec not generated")
def test_contract_core_endpoints():
    """Validate core API endpoints exist in OpenAPI schema."""
    with open(OPENAPI_PATH, "r") as f:
        openapi_spec = json.load(f)

    schema = schemathesis.openapi.from_dict(openapi_spec)
    ops = list(schema.get_all_operations())

    # Filter operations
    core_ops = []
    for op_result in ops:
        op = op_result._value
        if (
            op.path.startswith("/projects")
            or op.path.startswith("/golden")
            or op.path == "/health"
            or op.path == "/config/contracts/reload"
        ):
            core_ops.append(f"{op.method.upper()} {op.path}")

    # Validate we have expected paths
    expected = {
        "POST /projects/",
        "GET /projects/",
        "GET /projects/{project_id}",
        "POST /golden/contribute",
        "GET /golden/samples",
        "GET /health",
    }

    found = set(core_ops)
    missing = expected - found
    if missing:
        print(f"\nMISSING: {missing}")
    else:
        print("\nAll expected core endpoints found in schema!")

    print(f"\nTotal operations: {len(ops)}")
    assert not missing, f"Missing expected endpoints: {missing}"
