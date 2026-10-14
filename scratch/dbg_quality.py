import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.audiobook_studio.feedback.canary import check_input_compatibility, _convert_input_to_model, _get_required_input_fields
print("required fields (quality):", _get_required_input_fields("quality"))
ok, why = check_input_compatibility("quality", {"audio_path": "a.wav", "expected_text": "你好"})
print("ok:", ok)
print("why:", why[:600])
