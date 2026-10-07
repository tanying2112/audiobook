import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
mods = [
    "src.audiobook_studio.feedback.candidate_eval",
    "src.audiobook_studio.feedback.promotion",
    "src.audiobook_studio.feedback.promotion_gate",
    "src.audiobook_studio.feedback.canary",
    "src.audiobook_studio.feedback.offline_judge",
    "src.audiobook_studio.feedback.integration",
    "src.audiobook_studio.feedback.pr_automation",
    "src.audiobook_studio.harness.spotcheck",
]
import importlib
for m in mods:
    importlib.import_module(m)
    print("IMPORT OK", m)
print("ALL_IMPORTS_OK")
