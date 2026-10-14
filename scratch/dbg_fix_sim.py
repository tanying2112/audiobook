from pathlib import Path
p = Path("scratch/verify_pr_contract.py")
src = p.read_text(encoding="utf-8")
old = '''def _proc(rc=0, stdout="", stderr=""):
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = rc
    m.stdout = stdout
    m.stderr = stderr
    return m'''
new = '''def _proc(rc=0, stdout=None, stderr=None):
    """rc 恒设；stdout/stderr 不传则保持 auto-MagicMock（复刻原测试：成功路径
    的 stdout 是 MagicMock 而非 str，正是实现必须归一化处理的对象）。"""
    m = MagicMock(spec=subprocess.CompletedProcess)
    m.returncode = rc
    if stdout is not None:
        m.stdout = stdout
    if stderr is not None:
        m.stderr = stderr
    return m'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("sim fixed")
