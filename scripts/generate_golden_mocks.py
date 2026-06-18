import os
import json

stages = [
    "extract", "analyze_structure", "annotate_paragraph", 
    "edit_for_tts", "synthesize", "quality_check"
]
base_dir = "tests/golden"

for stage in stages:
    os.makedirs(f"{base_dir}/{stage}", exist_ok=True)
    for i in range(1, 4):
        file_path = f"{base_dir}/{stage}/case_{i}.json"
        
        # Simple mock payload structure based on standard pipeline schemas
        data = {
            "id": f"{stage}_case_{i}",
            "description": f"Mock case {i} for {stage}",
            "input": {"text": f"This is a test input for {stage} case {i}."},
            "expected_output": {"status": "success", "length": 50}
        }
        
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

print("Generated 18 golden dataset JSON cases.")
