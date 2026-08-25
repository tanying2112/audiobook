"""Multimodal (vision) image understanding — Task 4: 图文混排书籍解析.

提供方发现 + 单张图像理解客户端。这是 *真正的* 多模态理解（能读懂插图/图表/地图
/照片，不只是抠文字），区别于 tesseract OCR。

关键架构约束
------------
LLMRouter.call() 会把 messages[-1]["content"] 压缩成字符串再经 _build_messages()
重建，**丢弃任何 image content block** —— 所以视觉调用不能走现有 router。这里
独立实现：复用 ProviderConfig（config_loader）做提供方发现与 key/base_url 解析，但
用原生 OpenAI SDK 直接发 ``image_url`` 内容块。

诚实降级 (主路径真实性)
----------------------
本环境没有可达的免费视觉提供方时（key 缺失 / 网络不可达 / 模型 EOL），
``understand_image()`` 返回 ``None``，绝不伪造成功。调用方据此如实降级为文本层 /
抛错，与 extract.py 现有 OCR 的诚实降级一脉相承。
"""

import base64
import json
import logging
import os
import time
from typing import List, Optional

from ..schemas import VisualElement

logger = logging.getLogger(__name__)

# 让 LLM 返回结构化 JSON 的提示词。图片作为 image_url 内容块注入，文本提示紧随其后。
_DEFAULT_PROMPT = (
    "你是书籍图文解析助手。请分析这张图：\n"
    "1) 逐字转写图中所有文字（包括中文），放入 extracted_text；\n"
    "2) 用一句话中文描述这张图的性质与内容，放入 caption；\n"
    "3) 判断 kind：text(纯文字/文字截图)、figure(插图/示意图)、table(表格)、"
    "map(地图)、photo(照片/实拍)、other(其他)。\n"
    "只输出一个合法 JSON 对象，形如 "
    '{"kind":"figure","caption":"…","extracted_text":"…"}，不要输出任何其他文字、解释或代码块标记。'
)


def _sniff_media_type(image_bytes: bytes) -> str:
    """从文件头嗅探媒体类型，缺省 image/png。"""
    if image_bytes[:4] == b"\x89PNG":
        return "image/png"
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:4] == b"II*\x00" or image_bytes[:4] == b"MM\x00*":
        return "image/tiff"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _parse_visual_element(raw_text: str) -> Optional[VisualElement]:
    """防御性解析 LLM 返回的 JSON -> VisualElement。

    LLM 常不守 JSON 契约：先试完整 JSON，再试从文本中抽取最外层 {} 块。
    仍失败则把原文作为 caption 兜底 (kind=other)，不丢信息。
    """
    text = (raw_text or "").strip()
    if not text:
        return None

    def _extract_json(s: str):
        s = s.strip()
        if s.startswith("```"):
            # strip ```json ... ``` fences
            s = s.split("```")[1] if "```" in s[3:] else s
            s = s.strip()
        # try full parse
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        # try to find the outermost {...}
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(s[start : end + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        return None

    obj = _extract_json(text)
    if obj:
        kind = obj.get("kind", "other")
        if kind not in {"text", "figure", "table", "map", "photo", "other"}:
            kind = "other"
        return VisualElement(
            kind=kind,
            caption=str(obj.get("caption", "") or ""),
            extracted_text=str(obj.get("extracted_text", "") or ""),
        )
    # 未能解析成 JSON —— 把原文作为 caption 兜底，保证信息不丢、绝不静默丢弃。
    return VisualElement(kind="other", caption=text, extracted_text="")


class MultimodalVisionClient:
    """多模态视觉客户端：对单张图像产出 VisualElement。

    从 config/llm_providers.yaml 中发现 extra_params.vision=true 的提供方，
    按 priority 顺序逐个尝试，首个成功即返回。
    """

    def __init__(self, config_path: Optional[str] = None, mock_mode: Optional[bool] = None):
        if mock_mode is None:
            self.mock_mode = os.environ.get("MOCK_LLM", "false").lower() == "true"
        else:
            self.mock_mode = mock_mode

        from ..llm.config_loader import LLMProvidersConfig

        self.config = LLMProvidersConfig.load(config_path)
        self.providers: List = [
            p for p in self.config.get_all_enabled() if p.extra_params.get("vision")
        ]

    @property
    def available(self) -> bool:
        """是否有配置且启用的视觉提供方。"""
        return bool(self.providers)

    @property
    def provider_names(self) -> List[str]:
        return [p.name for p in self.providers]

    def understand_image(
        self,
        image_bytes: bytes,
        media_type: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> Optional[VisualElement]:
        """分析一张图像，返回 VisualElement；无可达视觉提供方或失败时返回 None。

        Args:
            image_bytes: 图像原始字节（PNG/JPG/...）。
            media_type: 图像 MIME，缺省从字节嗅探。
            prompt: 自定义提示词，缺省用内置 JSON 契约提示。
        """
        if self.mock_mode:
            return VisualElement(
                kind="other", caption="[mock] 多模态视觉理解", extracted_text="Mock vision text"
            )
        if not self.available:
            logger.warning(
                "Vision unavailable: no vision-capable provider configured "
                "(set extra_params.vision=true on a provider in config/llm_providers.yaml). "
                "Image understanding degraded honestly to text-layer/OCR-only."
            )
            return None

        media_type = media_type or _sniff_media_type(image_bytes)
        data_uri = f"data:{media_type};base64," + base64.b64encode(image_bytes).decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt or _DEFAULT_PROMPT},
                ],
            }
        ]

        last_err: Optional[Exception] = None
        for prov in self.providers:
            start = time.time()
            try:
                element = self._call_provider(prov, messages)
                latency_ms = int((time.time() - start) * 1000)
                if element is not None:
                    logger.info(
                        f"[vision] provider={prov.name} model={prov.model} "
                        f"kind={element.kind} chars={len(element.extracted_text)} "
                        f"latency={latency_ms}ms"
                    )
                    return element
                last_err = RuntimeError(f"{prov.name} returned no element")
            except Exception as e:  # noqa: BLE001 — 任一提供方失败都降级到下一个
                last_err = e
                logger.warning(f"[vision] provider {prov.name} failed: {e}")

        logger.warning(f"[vision] all vision providers failed (last: {last_err}); returning None")
        return None

    def _call_provider(self, prov, messages: list) -> Optional[VisualElement]:
        """对单个提供方发起视觉调用并解析。"""
        try:
            from openai import OpenAI
        except ImportError:
            logger.error("openai SDK not installed; cannot run vision")
            return None

        api_key = prov.get_api_key() or os.getenv(prov.api_key_env or "")
        timeout = (prov.timeout_seconds or 90) or None
        client = OpenAI(api_key=api_key or "", base_url=prov.base_url, timeout=timeout, max_retries=1)

        resp = client.chat.completions.create(
            model=prov.model,
            messages=messages,
            temperature=0.1,
            max_tokens=800,
        )
        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            return None
        return _parse_visual_element(content)


# ── Module-level singleton (与 LLMRouter 同构) ────────────────────────────────
_VISION_INSTANCE: Optional[MultimodalVisionClient] = None


def get_vision_client(config_path: Optional[str] = None) -> MultimodalVisionClient:
    """返回进程级 MultimodalVisionClient 单例（懒创建）。"""
    global _VISION_INSTANCE
    if _VISION_INSTANCE is None:
        _VISION_INSTANCE = MultimodalVisionClient(config_path)
    return _VISION_INSTANCE


def reset_vision_client() -> None:
    """丢弃缓存单例（供测试/应用关闭）。"""
    global _VISION_INSTANCE
    _VISION_INSTANCE = None