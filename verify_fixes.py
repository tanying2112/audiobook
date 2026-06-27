#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')
from audiobook_studio.llm.router import LLMRouter
from audiobook_studio.schemas import QualityJudgment

router = LLMRouter(mock_mode=True)

# Test 1: fallback with segment_id
result = router._heuristic_fallback('judge', QualityJudgment, segment_id='test_seg_123')
print(f'Test 1 - Fallback with segment_id: {result.segment_id}')
assert result.segment_id == 'test_seg_123', f'FAIL: Expected test_seg_123, got {result.segment_id}'

# Test 2: fallback without segment_id (default)
result2 = router._heuristic_fallback('judge', QualityJudgment)
print(f'Test 2 - Fallback default segment_id: {result2.segment_id}')
assert result2.segment_id == 'unknown', f'FAIL: Expected unknown, got {result2.segment_id}'

# Test 3: fallback for other stages still works
result3 = router._heuristic_fallback('analyze', QualityJudgment)
print(f'Test 3 - Fallback for analyze: {type(result3).__name__}')
assert result3 is not None, 'FAIL: analyze fallback should not be None'

print('✅ All fallback tests passed')