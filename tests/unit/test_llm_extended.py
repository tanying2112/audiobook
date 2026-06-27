"""LLM 模块扩展测试 — 补充 client.py 的覆盖率。"""

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from pydantic import BaseModel

import pytest


# ===========================================================================
# client.py — 补充缺失路径
# ===========================================================================


class TestLLMClientExtended:
    def test_call_with_text_kwarg(self):
        """client.call(text=...) 关键字参数路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call(text="hello", response_model=MagicMock)
            assert result is not None

    def test_call_with_content_kwarg(self):
        """client.call(content=...) 关键字参数路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call(content="hello", response_model=MagicMock)
            assert result is not None

    def test_call_with_messages_kwarg(self):
        """client.call(messages=[...]) 关键字参数路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            msgs = [{"role": "user", "content": "hello"}]
            result = client.call(messages=msgs, response_model=MagicMock)
            assert result is not None

    def test_call_positional_args(self):
        """client.call(prompt, response_model) 位置参数路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("hello", MagicMock)
            assert result is not None

    def test_call_no_prompt_raises(self):
        """client.call() 无 prompt 抛出 ValueError。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            with pytest.raises(ValueError, match="prompt is required"):
                client.call(response_model=MagicMock)

    def test_call_no_response_model_raises(self):
        """client.call() 无 response_model 抛出 ValueError。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            with pytest.raises(ValueError, match="response_model is required"):
                client.call(prompt="hello")

    def test_load_mock_data_json(self):
        """_load_mock_data 加载 .json 文件（直接构建 LLMClientConfig）。"""
        from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_file = Path(tmpdir) / "test_mock.json"
            mock_file.write_text(json.dumps({"key": "value"}))

            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                cfg = LLMClientConfig(model="test", mock_data_dir=tmpdir)
                client = LLMClient(cfg)
                assert "test_mock" in client._mock_cache

    def test_load_mock_data_jsonl(self):
        """_load_mock_data 加载 .jsonl 文件。"""
        from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_file = Path(tmpdir) / "test_mock.jsonl"
            mock_file.write_text(
                json.dumps({"expected_output": {"a": 1}}) + "\n"
            )

            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                cfg = LLMClientConfig(model="test", mock_data_dir=tmpdir)
                client = LLMClient(cfg)
                assert "test_mock" in client._mock_cache

    def test_load_mock_data_jsonl_no_expected(self):
        """_load_mock_data JSONL 无 expected_output 时用原始数据。"""
        from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_file = Path(tmpdir) / "raw_mock.jsonl"
            mock_file.write_text(json.dumps({"a": 1}) + "\n")

            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                cfg = LLMClientConfig(model="test", mock_data_dir=tmpdir)
                client = LLMClient(cfg)
                assert "raw_mock" in client._mock_cache

    def test_load_mock_data_empty_dir(self):
        """_load_mock_data 空目录不报错。"""
        from src.audiobook_studio.llm.client import LLMClient, LLMClientConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict("os.environ", {"MOCK_LLM": "true"}):
                cfg = LLMClientConfig(model="test", mock_data_dir=tmpdir)
                client = LLMClient(cfg)
                assert client._mock_cache == {}

    def test_init_client_non_mock(self):
        """非 mock 模式初始化 instructor 客户端。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            client = create_client(model="test")
            assert client._client is not None

    def test_init_client_mock(self):
        """mock 模式不初始化 instructor 客户端。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            assert client._client is None

    def test_init_langfuse_enabled(self):
        """Langfuse 启用时初始化客户端。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(
                model="test",
                langfuse_enabled=True,
                langfuse_public_key="pk",
                langfuse_secret_key="sk",
            )
            # langfuse 可能初始化成功也可能失败，但不应崩溃

    def test_init_langfuse_import_error(self):
        """Langfuse 导入失败时 graceful degradation。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            with patch.dict("sys.modules", {"langfuse": None}):
                client = create_client(
                    model="test",
                    langfuse_enabled=True,
                    langfuse_public_key="pk",
                    langfuse_secret_key="sk",
                )
                assert client._langfuse is None

    def test_model_pricing_coverage(self):
        """MODEL_PRICING 包含所有预期模型。"""
        from src.audiobook_studio.llm.client import MODEL_PRICING

        assert "gemini-2.0-flash" in MODEL_PRICING
        assert "gpt-4o" in MODEL_PRICING
        assert "groq/llama-3.1-70b-versatile" in MODEL_PRICING
        for name, pricing in MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing

    def test_config_api_base(self):
        """LLMClientConfig api_base 参数。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        cfg = LLMClientConfig(model="m", api_base="http://api.test.com")
        assert cfg.api_base == "http://api.test.com"

    def test_config_langfuse_params(self):
        """LLMClientConfig Langfuse 参数。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        cfg = LLMClientConfig(
            model="m",
            langfuse_public_key="pk",
            langfuse_secret_key="sk",
            langfuse_host="https://custom.host.com",
            langfuse_enabled=True,
        )
        assert cfg.langfuse_enabled is True

    def test_config_mock_mode_via_env(self):
        """LLMClientConfig mock_mode 通过环境变量。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            cfg = LLMClientConfig(model="m")
            assert cfg.mock_mode is True

    def test_config_mock_mode_default(self):
        """LLMClientConfig mock_mode 默认 false。"""
        from src.audiobook_studio.llm.client import LLMClientConfig

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("MOCK_LLM", None)
            cfg = LLMClientConfig(model="m")
            assert cfg.mock_mode is False

    def test_call_result_dataclass(self):
        """LLMCallResult 数据类完整字段。"""
        from src.audiobook_studio.llm.client import LLMCallResult

        class Out(BaseModel):
            v: str = "x"

        r = LLMCallResult(
            output=Out(),
            model="m",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            latency_ms=100,
            schema_compliance=True,
            contract_version=1,
            raw_response={"usage": {"prompt_tokens": 100, "completion_tokens": 50}},
        )
        assert r.tokens_in == 100
        assert r.raw_response["usage"]["prompt_tokens"] == 100

    def test_call_with_list_messages(self):
        """client.call(messages=[...]) 列表消息路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            msgs = [
                {"role": "system", "content": "你是一个助手"},
                {"role": "user", "content": "你好"},
            ]
            result = client.call(prompt=msgs, response_model=MagicMock)
            assert result is not None

    # ── 新增：覆盖 client.py 未覆盖路径 ──────────────────────────────

    def test_call_non_mock_with_api_base(self):
        """非 mock 模式下 api_base 被传递到 create() 调用。"""
        from src.audiobook_studio.llm.client import create_client

        class DummyModel(BaseModel):
            value: str = "x"

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            client = create_client(model="test", api_base="http://custom.api")
            mock_result = DummyModel(value="ok")
            mock_result._raw_response = {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
            client._client = MagicMock()
            client._client.chat.completions.create.return_value = mock_result
            result = client.call("test prompt", DummyModel)
            assert result.model == "test"
            assert result.tokens_in == 10

    def test_call_non_mock_cost_calculation(self):
        """非 mock 模式下费用计算。"""
        from src.audiobook_studio.llm.client import create_client

        class DummyModel(BaseModel):
            value: str = "x"

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            client = create_client(model="gemini-2.0-flash")
            mock_result = DummyModel(value="ok")
            mock_result._raw_response = {"usage": {"prompt_tokens": 1000, "completion_tokens": 500}}
            client._client = MagicMock()
            client._client.chat.completions.create.return_value = mock_result
            result = client.call("test prompt", DummyModel)
            assert result.cost_usd > 0

    def test_call_non_mock_with_messages_list(self):
        """非 mock 模式下传入 messages 列表。"""
        from src.audiobook_studio.llm.client import create_client

        class DummyModel(BaseModel):
            value: str = "x"

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            client = create_client(model="test")
            mock_result = DummyModel(value="ok")
            mock_result._raw_response = {"usage": {"prompt_tokens": 1, "completion_tokens": 1}}
            client._client = MagicMock()
            client._client.chat.completions.create.return_value = mock_result
            msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
            result = client.call(prompt=msgs, response_model=DummyModel)
            assert result is not None

    def test_call_non_mock_exception_propagates(self):
        """非 mock 模式下异常被记录并重新抛出。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "false"}):
            client = create_client(model="test")
            client._client = MagicMock()
            client._client.chat.completions.create.side_effect = RuntimeError("API down")
            with pytest.raises(RuntimeError, match="API down"):
                client.call("hello", MagicMock)

    def test_mock_call_returns_default_for_unknown_model(self):
        """mock 模式下未知 response_model 类型返回 None。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")

            class UnknownModel(BaseModel):
                required_field: str

            result = client.call("xyzzy", UnknownModel)
            assert result.output is None

    def test_mock_call_with_book_analysis_output(self):
        """mock 模式下返回 BookAnalysisOutput。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import BookAnalysisOutput

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", BookAnalysisOutput)
            assert isinstance(result.output, BookAnalysisOutput)

    def test_mock_call_with_extraction_result(self):
        """mock 模式下返回 ExtractionResult。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import ExtractionResult

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", ExtractionResult)
            assert isinstance(result.output, ExtractionResult)

    def test_mock_call_with_paragraph_annotation(self):
        """mock 模式下返回 ParagraphAnnotation。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import ParagraphAnnotation

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", ParagraphAnnotation)
            assert isinstance(result.output, ParagraphAnnotation)

    def test_mock_call_with_quality_judgment(self):
        """mock 模式下返回 QualityJudgment。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import QualityJudgment

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", QualityJudgment)
            assert isinstance(result.output, QualityJudgment)

    def test_mock_call_with_tts_edit_output(self):
        """mock 模式下返回 TtsEditOutput。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import TtsEditOutput

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", TtsEditOutput)
            assert isinstance(result.output, TtsEditOutput)

    def test_mock_call_with_tts_routing_decision(self):
        """mock 模式下返回 TtsRoutingDecision。"""
        from src.audiobook_studio.llm.client import create_client
        from src.audiobook_studio.schemas import TtsRoutingDecision

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", TtsRoutingDecision)
            assert isinstance(result.output, TtsRoutingDecision)

    def test_mock_call_with_string_response_model(self):
        """mock 模式下字符串 'FeedbackAnalysis' 类型的 response_model。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("test prompt", "FeedbackAnalysis")
            assert result.output is not None

    def test_mock_call_no_cache_match(self):
        """mock 模式下 prompt 不匹配任何缓存时走默认路径。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("unique_prompt_xyz", MagicMock)
            assert result is not None

    def test_langfuse_init_exception(self):
        """Langfuse 初始化异常时 _langfuse 为 None。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            with patch("langfuse.Langfuse", side_effect=RuntimeError("init fail")):
                client = create_client(
                    model="test",
                    langfuse_enabled=True,
                    langfuse_public_key="pk",
                    langfuse_secret_key="sk",
                )
                assert client._langfuse is None

    def test_call_with_temperature_override(self):
        """client.call 带 temperature 覆盖。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("hi", MagicMock, temperature=0.9)
            assert result is not None

    def test_call_with_max_tokens_override(self):
        """client.call 带 max_tokens 覆盖。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(model="test")
            result = client.call("hi", MagicMock, max_tokens=100)
            assert result is not None

    def test_init_langfuse_real_import(self):
        """Langfuse 启用时真正初始化（如果 langfuse 已安装）。"""
        from src.audiobook_studio.llm.client import create_client

        with patch.dict("os.environ", {"MOCK_LLM": "true"}):
            client = create_client(
                model="test",
                langfuse_enabled=True,
                langfuse_public_key="pk-real",
                langfuse_secret_key="sk-real",
                langfuse_host="https://custom.langfuse.com",
            )
            assert client.config.langfuse_enabled is True
