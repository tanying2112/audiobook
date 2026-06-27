"""
Contract Testing using Schemathesis - Quick validation test
"""
import schemathesis
import json

with open('/tmp/openapi.json', 'r') as f:
    openapi_spec = json.load(f)

schema = schemathesis.openapi.from_dict(openapi_spec)
ops = list(schema.get_all_operations())

# Filter operations
core_ops = []
for op_result in ops:
    op = op_result._value
    if op.path.startswith('/projects') or op.path.startswith('/golden') or op.path == '/health' or op.path == '/config/contracts/reload':
        core_ops.append(f"{op.method.upper()} {op.path}")

print("Core operations found:")
for op in core_ops:
    print(f"  {op}")

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
