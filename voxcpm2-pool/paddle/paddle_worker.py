"""
VoxCPM2 Worker Core - 供 Modal/Lightning/Paddle 复用的核心 Worker 逻辑
精简自 kaggle_worker.py，去除 Kaggle 特有依赖
"""

import abc
import json
import os
import signal
import subprocess

# 1. PyTorch 2.6+ weights_only=True 兼容性修复
# 强制 torch.load 默认使用 weights_only=False，兼容旧格式模型文件
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional

import torch

# =====================================================================
# 🛡️ CRITICAL PATCHES: Must be executed BEFORE ANY other imports
# =====================================================================


# ⚠️ CRITICAL: Save the REAL original torch.load BEFORE any patching
# This must be the VERY FIRST thing to avoid recursion issues
_REAL_ORIGINAL_TORCH_LOAD = torch.load


# Create patched load function
def _patched_torch_load(*args, **kwargs):
    if "weights_only" not in kwargs:
        kwargs["weights_only"] = False
    # Use the REAL original to avoid recursion
    return _REAL_ORIGINAL_TORCH_LOAD(*args, **kwargs)


_patched_torch_load._patched_weights_only = True

# Apply patch to torch module
torch.load = _patched_torch_load
sys.modules["torch"].load = _patched_torch_load

# Print confirmation
print(f"[PATCH] torch.load patched: weights_only default = False", flush=True)
# Verify patch is active
import torch as _verify_torch

print(f"[PATCH] Verification: patch active = {torch.load is _patched_torch_load}", flush=True)

# 2. BlockMask 类型提示冲突修复：在 transformers 导入前注入 DummyBlockMask
# 解决 PyTorch 2.5+ 与 transformers 的 BlockMask | Tensor 类型提示冲突
import types

print(f"[DEBUG] About to apply BlockMask patch", flush=True)
import torch

print(f"[DEBUG] torch imported for BlockMask: True", flush=True)
try:
    # 1. 确保 torch.nn.attention 存在
    if not hasattr(torch.nn, "attention"):
        torch.nn.attention = types.ModuleType("attention")
        sys.modules["torch.nn.attention"] = torch.nn.attention

    # 2. 确保 flex_attention 模块存在
    try:
        import torch.nn.attention.flex_attention as flex_module
    except ImportError:
        flex_module = types.ModuleType("flex_attention")
        torch.nn.attention.flex_attention = flex_module
        sys.modules["torch.nn.attention.flex_attention"] = flex_module

    # 3. 强行将 BlockMask 绑定为 Dummy 类，防止 Python 将其解析为 Module 导致 Type Hint 报错
    if not hasattr(flex_module, "BlockMask") or not isinstance(getattr(flex_module, "BlockMask", None), type):

        class DummyBlockMask:
            pass

        flex_module.BlockMask = DummyBlockMask
        sys.modules["torch.nn.attention.flex_attention.BlockMask"] = DummyBlockMask
        print(f"[PATCH] Successfully mocked flex_attention.BlockMask to class type.", flush=True)
except Exception as patch_err:
    print(f"[PATCH] Failed to apply BlockMask patch: {patch_err}", flush=True)


# 3. VoxCPM 导入钩子：在 voxcpm 被 import 时立即补丁 torch.load
class _VoxCPMImportHook:
    def __init__(self):
        self._active = False

    def find_spec(self, name, path, target=None):
        if not self._active and (name == "voxcpm" or name.startswith("voxcpm.")):
            from importlib.util import spec_from_loader

            return spec_from_loader(name, self)
        return None

    def create_module(self, spec):
        import importlib
        import sys

        import torch

        if self._active:
            return None

        self._active = True
        try:
            # Ensure torch.load is patched using the REAL original
            if not getattr(torch.load, "_patched_weights_only", False):
                orig = torch.load

                def patched(*a, **kw):
                    if "weights_only" not in kw:
                        kw["weights_only"] = False
                    return orig(*a, **kw)

                patched._patched_weights_only = True
                torch.load = patched
                sys.modules["torch"].load = patched

            # Import the real voxcpm module
            mod = importlib.import_module(spec.name)

            # Patch voxcpm's torch reference
            if hasattr(mod, "torch"):
                mod.torch.load = torch.load

            # Patch any cached torch.load references
            for attr_name in dir(mod):
                try:
                    obj = getattr(mod, attr_name)
                    if callable(obj) and getattr(obj, "__module__", "") == "torch" and obj.__name__ == "load":
                        if not getattr(obj, "_patched_weights_only", False):
                            setattr(mod, attr_name, torch.load)
                except Exception:
                    pass

            return mod
        finally:
            self._active = False

    def exec_module(self, module):
        pass


# Install hook BEFORE any imports
sys.meta_path.insert(0, _VoxCPMImportHook())
print(f"[PATCH] Installed voxcpm import hook", flush=True)


# 🛡️ AGGRESSIVE POST-IMPORT PATCH: If voxcpm is already imported, re-patch it
# This catches the case where voxcpm was imported during bootstrap (pip install)
def _patch_all_voxcpm_torch_load():
    """Force patch ALL voxcpm modules in sys.modules"""
    import sys

    import torch

    patched_count = 0
    for name, mod in list(sys.modules.items()):
        if name == "voxcpm" or name.startswith("voxcpm."):
            # Patch mod.torch.load if exists
            if hasattr(mod, "torch") and hasattr(mod.torch, "load"):
                if not getattr(mod.torch.load, "_patched_weights_only", False):
                    mod.torch.load = torch.load
                    print(f"[PATCH] Patched {name}.torch.load", flush=True)
            # Also check for direct torch.load references (from torch import load)
            for attr_name in dir(mod):
                try:
                    obj = getattr(mod, attr_name)
                    if callable(obj) and getattr(obj, "__module__", "") == "torch" and obj.__name__ == "load":
                        if not getattr(obj, "_patched_weights_only", False):
                            setattr(mod, attr_name, torch.load)
                except Exception:
                    pass


# 🛡️ AGGRESSIVE POST-IMPORT PATCH: If voxcpm is already imported, re-patch it
# This catches the case where voxcpm was imported during bootstrap (pip install)
if "voxcpm" in sys.modules:
    import torch

    m = sys.modules["voxcpm"]
    if hasattr(m, "torch"):
        m.torch.load = torch.load
    for aname in dir(m):
        try:
            obj = getattr(m, aname)
            if callable(obj) and obj.__module__ == "torch" and obj.__name__ == "load":
                m.__dict__[aname] = torch.load
        except Exception:
            pass

import sys

os.environ["HF_HUB_DISABLE_SSL_VERIFY"] = "1"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import abc
