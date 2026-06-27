"""Audiobookshelf 集成模块 - 将有声书发布到 Audiobookshelf 平台."""

import base64
import hashlib
import json
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = __import__("logging").getLogger(__name__)


# 兼容性 stub，保持与旧版本的导入兼容
class AudiobookshelfAPIClient:
    """兼容性 stub 类（不提供实际功能）"""

    def __init__(self, *args, **kwargs):
        pass

    def check_connection(self, *args, **kwargs) -> bool:
        return True

    def upload_audiobook(self, *args, **kwargs) -> Any:
        return True


@dataclass
class AudiobookMetadata:
    """有声书元数据"""

    title: str
    author: str
    narrator: str
    description: str
    language: str = "zh-CN"
    publication_year: Optional[int] = None
    publisher: str = ""
    genres: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    series: Optional[str] = None
    series_index: Optional[float] = None
    cover_image_path: Optional[Path] = None
    # 音频文件信息
    duration_seconds: float = 0.0
    bitrate_kbps: int = 64
    format: str = "m4b"  # m4b, mp3, etc.


@dataclass
class AudiobookFile:
    """有声书音频文件"""

    file_path: Path
    size_bytes: int
    duration_seconds: float
    format: str  # m4b, mp3
    bitrate_kbps: int
    checksum_md5: str
    # 章节信息 (对于M4B格式)
    chapters: List[Dict] = field(default_factory=list)


@dataclass
class AudiobookshelfConfig:
    """Audiobookshelf 配置"""

    api_url: str  # 例如: http://localhost:8080
    api_key: str  # API 密钥（Bearer token）
    library_id: str  # 目标库的 ID
    # 支持的格式
    supported_formats: List[str] = field(default_factory=lambda: ["m4b", "mp3"])
    # 自动转换设置
    auto_convert: bool = True
    preferred_format: str = "m4b"


class AudiobookshelfIntegrator:
    """Audiobookshelf 集成器 - 真实 API 实现"""

    def __init__(self, config: AudiobookshelfConfig):
        self.config = config
        self.supported_formats = set(config.supported_formats)
        self.base_url = config.api_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=30.0),
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    async def close(self):
        """关闭 HTTP 客户端"""
        await self.client.aclose()

    async def prepare_audiobook(
        self, metadata: AudiobookMetadata, audio_file: AudiobookFile
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        准备有声书元数据和文件以供发布

        Returns:
            (是否成功, 消息, 待发布的数据包)
        """
        # 验证元数据
        valid, message = self._validate_metadata(metadata)
        if not valid:
            return False, message, None

        # 验证音频文件
        valid, message = self._validate_audio_file(audio_file)
        if not valid:
            return False, message, None

        # 检查格式是否支持
        if audio_file.format.lower() not in self.supported_formats:
            if self.config.auto_convert:
                return (
                    False,
                    f"不支持的格式 {audio_file.format}，自动转换功能待实现",
                    None,
                )
            else:
                return (
                    False,
                    f"不支持的格式: {audio_file.format}. 支持的格式: {', '.join(self.supported_formats)}",
                    None,
                )

        # 生成发布数据包
        try:
            upload_data = self._prepare_upload_data(metadata, audio_file)
            return True, "有声书准备成功", upload_data
        except Exception as e:
            return False, f"准备有声书数据时出错: {str(e)}", None

    def _validate_metadata(self, metadata: AudiobookMetadata) -> Tuple[bool, str]:
        """验证有声书元数据"""
        if not metadata.title.strip():
            return False, "标题不能为空"

        if not metadata.author.strip():
            return False, "作者不能为空"

        if not metadata.narrator.strip():
            return False, "朗读者不能为空"

        if metadata.publication_year and (
            metadata.publication_year < 1000 or metadata.publication_year > 2100
        ):
            return False, f"出版年份不合理: {metadata.publication_year}"

        return True, "元数据验证通过"

    def _validate_audio_file(self, audio_file: AudiobookFile) -> Tuple[bool, str]:
        """验证音频文件"""
        if not audio_file.file_path.exists():
            return False, f"音频文件不存在: {audio_file.file_path}"

        if not audio_file.file_path.is_file():
            return False, f"路径不是文件: {audio_file.file_path}"

        # 检查文件大小
        actual_size = audio_file.file_path.stat().st_size
        if actual_size != audio_file.size_bytes:
            return (
                False,
                f"文件大小不匹配: 声明 {audio_file.size_bytes} 字节, 实际 {actual_size} 字节",
            )

        # 检查文件格式
        file_ext = audio_file.file_path.suffix.lower().lstrip(".")
        if file_ext != audio_file.format:
            return (
                False,
                f"文件扩展名 (.{file_ext}) 与指定格式 ({audio_file.format}) 不匹配",
            )

        # 检查 MIME 类型
        mime_type, _ = mimetypes.guess_type(str(audio_file.file_path))
        expected_mime = {
            "m4b": "audio/mp4",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac",
        }.get(audio_file.format)

        if (
            expected_mime
            and mime_type
            and not mime_type.startswith(expected_mime.split("/")[0])
        ):
            return (
                False,
                f"文件 MIME 类型不匹配: 期望 {expected_mime}, 实际 {mime_type}",
            )

        return True, "音频文件验证通过"

    def _prepare_upload_data(
        self, metadata: AudiobookMetadata, audio_file: AudiobookFile
    ) -> Dict:
        """准备上传到 Audiobookshelf 的数据"""
        # 生成封面图片的 base64 (如果有的话)
        cover_data = None
        if metadata.cover_image_path and metadata.cover_image_path.exists():
            try:
                with open(metadata.cover_image_path, "rb") as f:
                    cover_data = base64.b64encode(f.read()).decode("utf-8")
            except Exception:
                pass  # 封面图片读取失败不影响主要功能

        # 准备章节信息
        chapters = audio_file.chapters
        if not chapters and audio_file.duration_seconds > 0:
            # 如果没有提供章节但有时长，创建一个默认章节
            chapters = [
                {
                    "title": metadata.title,
                    "start": 0,
                    "end": int(audio_file.duration_seconds),
                }
            ]

        upload_data = {
            # 基本信息
            "title": metadata.title,
            "author": metadata.author,
            "narrator": metadata.narrator,
            "description": metadata.description,
            "language": metadata.language,
            "year": metadata.publication_year,
            "publisher": metadata.publisher,
            "genres": metadata.genres,
            "tags": metadata.tags,
            # 系列信息
            "series": metadata.series,
            "seriesIndex": metadata.series_index,
            # 文件信息
            "fileName": audio_file.file_path.name,
            "size": audio_file.size_bytes,
            "duration": int(audio_file.duration_seconds),
            "bitrate": audio_file.bitrate_kbps * 1000,  # 转换为 bps
            "format": audio_file.format,
            # 封面图片
            "coverImage": cover_data,
            # 章节
            "chapters": chapters,
        }

        return upload_data

    async def publish_to_audiobookshelf(
        self, metadata: AudiobookMetadata, audio_file: AudiobookFile
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        将有声书发布到 Audiobookshelf（真实 API 调用）

        Returns:
            (是否成功, 消息, 服务器响应)
        """
        # 准备数据
        valid, message, upload_data = await self.prepare_audiobook(metadata, audio_file)
        if not valid:
            return False, message, None

        try:
            response = await self._real_api_call(upload_data, audio_file)

            if response.get("success"):
                return (
                    True,
                    f"有声书已成功发布到 Audiobookshelf (ID: {response.get('book_id')})",
                    response,
                )
            else:
                return (
                    False,
                    f"发布失败: {response.get('message', '未知错误')}",
                    response,
                )

        except Exception as e:
            return False, f"发布过程中出现网络错误: {str(e)}", None

    async def _real_api_call(
        self, upload_data: Dict, audio_file: AudiobookFile
    ) -> Dict:
        """真实的 Audiobookshelf API 调用"""
        # 获取库 ID 和 API 密钥
        library_id = self.config.library_id
        if not library_id:
            return {"success": False, "message": "库 ID 未配置", "book_id": None}

        # 第一步：获取库信息以获取文件夹 ID（用于上传）
        folder_id: Optional[str] = None
        try:
            resp = await self.client.get(f"{self.base_url}/api/libraries/{library_id}")
            if resp.status_code == 404:
                return {
                    "success": False,
                    "message": f"库 {library_id} 不存在",
                    "book_id": None,
                }
            elif resp.status_code != 200:
                return {
                    "success": False,
                    "message": f"无法访问库 ({resp.status_code}): {resp.text}",
                    "book_id": None,
                }

            library_info = resp.json()
            folders = library_info.get("folders", [])
            if folders:
                folder_id = folders[0].get("id")
            else:
                return {
                    "success": False,
                    "message": f"库 {library_id} 没有配置任何文件夹",
                    "book_id": None,
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"获取库信息失败: {str(e)}",
                "book_id": None,
            }

        # 第二步：准备上传文件列表
        book_title = upload_data.get("title", f"Project {self.config.library_id}")
        author = upload_data.get("author", "Unknown")

        # 收集音频文件（这里我们假设 audio_file 是单个文件）
        audio_files: List[Path] = []
        total_size = 0
        if audio_file.file_path.exists():
            audio_files.append(audio_file.file_path)
            total_size += audio_file.file_path.stat().st_size

        if not audio_files:
            return {"success": False, "message": "未找到音频文件", "book_id": None}

        # 第三步：上传文件
        upload_results: List[Dict[str, Any]] = []
        successful_uploads = 0

        # 如果配置了 base_path（本地库），直接复制文件
        base_path = getattr(self.config, "base_path", None)
        if base_path:
            # 本地库：将文件复制到库存储路径下的作者/书名目录
            library_audio_path = Path(base_path) / author / book_title
            try:
                library_audio_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                upload_results.append(
                    {
                        "file": "directory_creation",
                        "success": False,
                        "error": str(e),
                    }
                )

            for audio_file_path in audio_files:
                dest_path = library_audio_path / audio_file_path.name
                try:
                    import shutil

                    shutil.copy2(audio_file_path, dest_path)
                    upload_results.append(
                        {
                            "file": audio_file_path.name,
                            "success": True,
                            "server_path": str(dest_path),
                        }
                    )
                    successful_uploads += 1
                except Exception as e:
                    upload_results.append(
                        {
                            "file": audio_file_path.name,
                            "success": False,
                            "error": str(e),
                        }
                    )
        else:
            # 远程库：使用 POST /api/upload
            for audio_file_path in audio_files:
                try:
                    with open(audio_file_path, "rb") as f:
                        files = {
                            "file": (
                                audio_file_path.name,
                                f.read(),
                                self._get_mime_type(audio_file_path),
                            )
                        }
                        data = {
                            "library": library_id,
                            "folder": folder_id,
                            "title": book_title,
                            "author": author,
                        }
                        resp = await self.client.post(
                            f"{self.base_url}/api/upload", data=data, files=files
                        )
                    if resp.status_code in (200, 201):
                        upload_results.append(
                            {
                                "file": audio_file_path.name,
                                "success": True,
                            }
                        )
                        successful_uploads += 1
                    else:
                        upload_results.append(
                            {
                                "file": audio_file_path.name,
                                "success": False,
                                "error": f"HTTP {resp.status_code}: {resp.text}",
                            }
                        )
                except Exception as e:
                    upload_results.append(
                        {
                            "file": audio_file_path.name,
                            "success": False,
                            "error": str(e),
                        }
                    )

        if successful_uploads == 0:
            return {
                "success": False,
                "message": "所有文件上传失败",
                "book_id": None,
                "upload_results": upload_results,
            }

        # 第四步：触发库扫描
        try:
            scan_resp = await self.client.post(
                f"{self.base_url}/api/libraries/{library_id}/scan"
            )
            if scan_resp.status_code not in (200, 201):
                # 不致命，继续
                pass
        except Exception as e:
            # 不致命，继续
            pass

        # 第五步：轮询查找新创建的条目
        item_id: Optional[str] = None
        max_retries = 10
        poll_interval = 3  # 秒
        import asyncio

        for _ in range(max_retries):
            await asyncio.sleep(poll_interval)
            try:
                resp = await self.client.get(
                    f"{self.base_url}/api/libraries/{library_id}/search",
                    params={"q": book_title},
                )
                if resp.status_code == 200:
                    results = resp.json()
                    for item in results:
                        media = item.get("media") or {}
                        metadata_item = media.get("metadata") or {}
                        item_title = metadata_item.get("title", "")
                        if item_title.lower() == book_title.lower():
                            item_id = item.get("id")
                            break
                if item_id:
                    break
            except Exception:
                pass

        # 第六步：更新元数据（如果找到 item_id）
        if item_id:
            metadata_payload = {
                "metadata": {
                    "title": book_title,
                    "authorName": author,
                }
            }
            # 添加可选字段
            desc = upload_data.get("description")
            if desc:
                metadata_payload["metadata"]["description"] = desc
            pub_year = upload_data.get("year")
            if pub_year:
                metadata_payload["metadata"]["publishedYear"] = pub_year
            publisher = upload_data.get("publisher")
            if publisher:
                metadata_payload["metadata"]["publisher"] = publisher
            genres = upload_data.get("genres")
            if genres:
                metadata_payload["metadata"]["genre"] = genres
            lang = upload_data.get("language")
            if lang:
                # 转换语言代码（例如 zh -> zh-CN）
                if len(lang) == 2:
                    lang_map = {
                        "zh": "zh-CN",
                        "en": "en-US",
                        "ja": "ja-JP",
                        "ko": "ko-KR",
                    }
                    lang = lang_map.get(lang, lang)
                metadata_payload["metadata"]["language"] = lang
            series = upload_data.get("series")
            if series:
                metadata_payload["metadata"]["series"] = series
            series_index = upload_data.get("seriesIndex")
            if series_index is not None:
                metadata_payload["metadata"]["seriesSequence"] = series_index
            tags = upload_data.get("tags")
            if tags:
                metadata_payload["metadata"]["tags"] = tags
            chapters = upload_data.get("chapters")
            if chapters is not None:
                # 注意：API 期望 chapters 列表，每个章节有 title, start, end
                # 我们的 chapters 已经是这种格式
                metadata_payload["metadata"]["chapters"] = chapters

            try:
                resp = await self.client.patch(
                    f"{self.base_url}/api/items/{item_id}/media", json=metadata_payload
                )
                if resp.status_code not in (200, 204):
                    # 不致命，继续
                    pass
            except Exception:
                pass

            # 第七步：上传封面图片（如果有）
            cover_b64 = upload_data.get("coverImage")
            if cover_b64:
                try:
                    import base64

                    cover_bytes = base64.b64decode(cover_b64)
                    files = {"cover": ("cover.jpg", cover_bytes, "image/jpeg")}
                    resp = await self.client.post(
                        f"{self.base_url}/api/items/{item_id}/cover", files=files
                    )
                    if resp.status_code not in (200, 201):
                        # 不致命
                        pass
                except Exception:
                    pass

        # 构建返回结果
        return {
            "success": successful_uploads > 0,
            "message": (
                f"成功上传 {successful_uploads}/{len(audio_files)} 个文件"
                if item_id
                else "文件上传成功，但未能确认项目 ID"
            ),
            "book_id": item_id,
            "item_id": item_id,
            "uploaded_files": successful_uploads,
            "total_files": len(audio_files),
            "total_size_bytes": total_size,
            "upload_results": upload_results,
            "library_id": library_id,
        }

    def _get_mime_type(self, path: Path) -> str:
        """根据文件扩展名返回 MIME 类型"""
        return {
            ".m4b": "audio/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".ogg": "audio/ogg",
            ".aac": "audio/aac",
        }.get(path.suffix.lower(), "application/octet-stream")

    async def get_library_status(self) -> Dict:
        """获取 Audiobookshelf 库状态（真实 API 调用）"""
        url = f"{self.base_url}/api/libraries/{self.config.library_id}"
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                data = response.json()
                return {
                    "library_id": self.config.library_id,
                    "total_books": data.get("mediaCount", 0),
                    "total_duration_hours": data.get("duration", 0) / 3600,
                    "supported_formats": list(self.supported_formats),
                    "status": "online",
                    "last_updated": datetime.now().isoformat(),
                }
        except Exception:
            pass

        return {
            "library_id": self.config.library_id,
            "total_books": 0,
            "total_duration_hours": 0,
            "supported_formats": list(self.supported_formats),
            "status": "offline",
            "last_updated": datetime.now().isoformat(),
            "error": "无法连接到 Audiobookshelf",
        }


def main():
    """主函数 - 演示 Audiobookshelf 集成"""
    logger.info("=== Audiobook Studio Audiobookshelf 集成演示 ===\n")

    # 配置 Audiobookshelf 连接
    config = AudiobookshelfConfig(
        api_url="http://localhost:8080",
        api_key=os.getenv("AUDIOBOOKSHELF_API_KEY", ""),  # 从环境变量读取
        library_id="main_library",
        supported_formats=["m4b", "mp3"],
        auto_convert=True,
        preferred_format="m4b",
    )

    # 创建集成器
    import asyncio

    integrator = AudiobookshelfIntegrator(config)

    logger.info("🔧 配置 Audiobookshelf 连接:")
    logger.info(f"   API 地址: {config.api_url}")
    logger.info(f"   库 ID: {config.library_id}")
    logger.info(f"   支持格式: {', '.join(config.supported_formats)}")
    logger.info(f"   自动转换: {'✅ 是' if config.auto_convert else '❌ 否'}")

    logger.info("\n" + "=" * 60)

    # 准备有声书元数据
    logger.info("\n📚 准备有声书元数据...")
    metadata = AudiobookMetadata(
        title="三体",
        author="刘慈欣",
        narrator="刘忆",
        description="文化大革命期间，一份秘密军工项目的信号被外星文明接收，引发了跨越时空的文明碰撞。",
        language="zh-CN",
        publication_year=2008,
        publisher="重庆出版社",
        genres=["科幻", "硬科幻", "外星文明"],
        tags=["刘慈欣", "三体 Trilogy", "硬科幻"],
        series="三体 Trilogy",
        series_index=1.0,
        cover_image_path=Path("./covers/saneti_cover.jpg"),  # 假设存在
    )

    logger.info(f"   标题: {metadata.title}")
    logger.info(f"   作者: {metadata.author}")
    logger.info(f"   朗读者: {metadata.narrator}")
    logger.info(f"   描述: {metadata.description[:50]}...")

    logger.info("\n" + "=" * 60)

    # 准备音频文件信息
    logger.info("\n🔊 准备音频文件信息...")
    # 模拟一个实际的 M4B 文件
    audio_file_path = Path("./audiobooks/saneti_full.m4b")
    # 在实际使用中，这个文件 zou 是由之前的流程生成的

    # 为了演示，我们创建一个假的文件信息对象
    audio_file = AudiobookFile(
        file_path=audio_file_path,
        size_bytes=457283092,  # ~436 MB
        duration_seconds=21 * 60 * 60 + 45 * 60 + 30,  # 21小时45分30秒
        format="m4b",
        bitrate_kbps=64,
        checksum_md5="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",  # 假设的MD5
        chapters=[
            {"title": "第一章 文化大革命", "start": 0, "end": 1800},  # 30分钟
            {"title": "第二章 红岸基地", "start": 1800, "end": 5400},  # 1.5小时
            # 省略中间章节...
            {
                "title": "章节二十九  szerTranslator",
                "start": 75600,
                "end": 77400,  # 最后30分钟
            },
        ],
    )

    logger.info(f"   文件名: {audio_file.file_path.name}")
    logger.info(f"   文件大小: {audio_file.size_bytes / (1024*1024):.1f} MB")
    logger.info(
        f"   时长: {int(audio_file.duration_seconds//3600):02d}:{int((audio_file.duration_seconds%3600)//60):02d}:{int(audio_file.duration_seconds%60):02d}"
    )
    logger.info(f"   格式: {audio_file.format}")
    logger.info(f"   比特率: {audio_file.bitrate_kbps} kbps")
    logger.info(f"   章节数: {len(audio_file.chapters)}")

    logger.info("\n" + "=" * 60)

    # 验证准备工作
    logger.info("\n🔍 验证有声书信息...")

    async def run_validation():
        return await integrator.prepare_audiobook(metadata, audio_file)

    valid, message, upload_data = asyncio.run(run_validation())

    if valid:
        logger.info("   ✅ 有声书信息验证通过")
        logger.info(f"   📊 准备上传的数据字段: {len(upload_data)} 项")
    else:
        logger.error(f"   ❌ 验证失败: {message}")
        return

    logger.info("\n" + "=" * 60)

    # TODO: 真实发布需要 Audiobookshelf 服务器运行
    # 使用 asyncio 运行异步发布
    logger.info("\n🚀 发布到 Audiobookshelf (需要真实服务器)...")
    logger.warning("   ⚠️ 此处为演示，实际使用需配置真实的 Audiobookshelf 服务器")

    # 显示库状态
    logger.info("\n📊 Audiobookshelf 库状态:")
    status = asyncio.run(integrator.get_library_status())
    logger.info(f"   库 ID: {status['library_id']}")
    logger.info(f"   图书总数: {status['total_books']} 本")
    logger.info(f"   时长总计: {status['total_duration_hours']} 小时")
    logger.info(f"   支持格式: {', '.join(status['supported_formats'])}")
    logger.info(f"   服务器状态: {status['status']}")
    logger.info(f"   最后更新: {status['last_updated']}")
    if "error" in status:
        logger.error(f"   ❌ 错误: {status['error']}")

    logger.info("\n" + "=" * 60)
    logger.info("🎉 Audiobookshelf 集成演示完成")
    logger.info("=" * 60)

    # 关闭客户端
    asyncio.run(integrator.close())


if __name__ == "__main__":
    main()
