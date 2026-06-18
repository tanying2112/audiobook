"""Audiobookshelf 集成模块 - 将有声书发布到 Audiobookshelf 平台."""

import json
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import hashlib

logger = logging.getLogger(__name__)


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
    api_url: str  # 例如: http://localhost:8080/api
    api_key: str  # API 密钥
    library_id: str  # 目标库的 ID
    # 支持的格式
    supported_formats: List[str] = field(default_factory=lambda: ["m4b", "mp3"])
    # 自动转换设置
    auto_convert: bool = True
    preferred_format: str = "m4b"


class AudiobookshelfPublisher:
    """Audiobookshelf 发布器"""

    def __init__(self, config: AudiobookshelfConfig):
        self.config = config
        self.supported_formats = set(config.supported_formats)
        logger.info("🔊 Audiobookshelf 发布器初始化完成")

    def publish_audiobook(
        self,
        metadata: AudiobookMetadata,
        audio_file: AudiobookFile
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        将有声书发布到 Audiobookshelf

        Returns:
            (是否成功, 消息, 服务器响应)
        """
        logger.info(f"🚀 开始发布有声书到 Audiobookshelf: {metadata.title}")

        # 准备数据
        valid, message, upload_data = self._prepare_audiobook(metadata, audio_file)
        if not valid:
            logger.error(f"❌ 有声书准备失败: {message}")
            return False, message, None

        # 在实际实现中，这里 zou 发送 HTTP 请求到 Audiobookshelf API
        # 为演示目的，我们模拟这个过程

        try:
            # 模拟API调用
            response = self._mock_api_call(upload_data)

            if response.get("success"):
                success_msg = f"有声书已成功发布到 Audiobookshelf (ID: {response.get('book_id')})"
                logger.info(f"✅ {success_msg}")
                return True, success_msg, response
            else:
                error_msg = f"发布失败: {response.get('message', '未知错误')}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg, response

        except Exception as e:
            error_msg = f"发布过程中出现网络错误: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None

    def _prepare_audiobook(
        self,
        metadata: AudiobookMetadata,
        audio_file: AudiobookFile
    ) -> Tuple[bool, str, Optional[Dict]]:
        """
        准备有声书元数据和文件以供发布

        Returns:
            (是否成功, 消息, 待发布的数据包)
        """
        logger.debug("🔍 验证有声书元数据和音频文件")

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
                # 在实际实现中，这里 zou 进行格式转换
                warning_msg = f"不支持的格式 {audio_file.format}，自动转换功能待实现"
                logger.warning(f"⚠️ {warning_msg}")
                return False, warning_msg, None
            else:
                error_msg = f"不支持的格式: {audio_file.format}. 支持的格式: {', '.join(self.supported_formats)}"
                logger.error(f"❌ {error_msg}")
                return False, error_msg, None

        # 生成发布数据包
        try:
            upload_data = self._prepare_upload_data(metadata, audio_file)
            logger.debug(f"📦 有声书数据准备完成，包含 {len(upload_data)} 个字段")
            return True, "有声书准备成功", upload_data
        except Exception as e:
            error_msg = f"准备有声书数据时出错: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None

    def _validate_metadata(self, metadata: AudiobookMetadata) -> Tuple[bool, str]:
        """验证有声书元数据"""
        if not metadata.title.strip():
            return False, "标题不能为空"

        if not metadata.author.strip():
            return False, "作者不能为空"

        if not metadata.narrator.strip():
            return False, "朗读者不能为空"

        if metadata.publication_year and (metadata.publication_year < 1000 or metadata.publication_year > 2100):
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
            return False, f"文件大小不匹配: 声明 {audio_file.size_bytes} 字节, 实际 {actual_size} 字节"

        # 检查文件格式
        file_ext = audio_file.file_path.suffix.lower().lstrip('.')
        if file_ext != audio_file.format:
            return False, f"文件扩展名 (.{file_ext}) 与指定格式 ({audio_file.format}) 不匹配"

        # 检查MIME类型
        mime_type, _ = mimetypes.guess_type(str(audio_file.file_path))
        expected_mime = {
            "m4b": "audio/mp4",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "flac": "audio/flac"
        }.get(audio_file.format)

        if expected_mime and mime_type and not mime_type.startswith(expected_mime.split('/')[0]):
            return False, f"文件MIME类型不匹配: 期望 {expected_mime}, 实际 {mime_type}"

        return True, "音频文件验证通过"

    def _prepare_upload_data(
        self,
        metadata: AudiobookMetadata,
        audio_file: AudiobookFile
    ) -> Dict:
        """准备上传到 Audiobookshelf 的数据"""
        logger.debug("📋 准备 Audiobookshelf 上传数据")

        # 生成封面图片的 base64 (如果有的话)
        cover_data = None
        if metadata.cover_image_path and metadata.cover_image_path.exists():
            try:
                import base64
                with open(metadata.cover_image_path, "rb") as f:
                    cover_data = base64.b64encode(f.read()).decode('utf-8')
            except Exception as e:
                logger.warning(f"⚠️ 封面图片读取失败: {e}")

        # 准备章节信息
        chapters = audio_file.chapters
        if not chapters and audio_file.duration_seconds > 0:
            # 如果没有提供章节但有时长，创建一个默认章节
            chapters = [{
                "title": metadata.title,
                "start": 0,
                "end": int(audio_file.duration_seconds)
            }]

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
            "chapters": chapters
        }

        return upload_data

    def _mock_api_call(self, upload_data: Dict) -> Dict:
        """模拟 Audiobookshelf API 调用"""
        logger.debug("📡 模拟 Audiobookshelf API 调用")

        # 在实际实现中，这 zou 是一个 HTTP POST 请求到
        # {self.config.api_url}/books 或者类似的端点

        # 检查是否已存在相同标题和作者的书籍（简化检查）
        book_title = upload_data.get("title", "").lower()
        book_author = upload_data.get("author", "").lower()

        # 生成一个假的书籍ID
        book_string = f"{book_title}|{book_author}"
        book_id = hashlib.md5(book_string.encode()).hexdigest()[:12]

        # 模拟偶尔的失败（例如网络问题或重复书籍）
        import random
        if random.random() < 0.1:  # 10% 的失败率用于演示
            return {
                "success": False,
                "message": "网络连接超时，请稍后重试",
                "book_id": None
            }

        # 检查是否是重复书籍（简化逻辑）
        if random.random() < 0.05:  # 5% 的概率报告为重复
            return {
                "success": False,
                "message": f"书籍已存在: 《{upload_data.get('title')}》 by {upload_data.get('author')}",
                "book_id": book_id,
                "is_duplicate": True
            }

        # 成功响应
        return {
            "success": True,
            "message": "书籍已成功导入",
            "book_id": book_id,
            "import_id": hashlib.md5(f"{book_id}{datetime.now()}".encode()).hexdigest()[:16],
            "book": {
                "id": book_id,
                "title": upload_data.get("title"),
                "author": upload_data.get("author"),
                "narrator": upload_data.get("narrator"),
                "duration": upload_data.get("duration"),
                "addedAt": datetime.now().isoformat(),
                "updatedAt": datetime.now().isoformat()
            }
        }

    def get_library_status(self) -> Dict:
        """获取 Audiobookshelf 库状态（模拟）"""
        logger.debug("📊 获取 Audiobookshelf 库状态")
        # 在实际实现中，这 zou 是一个 GET 请求到 /library 端点
        return {
            "library_id": self.config.library_id,
            "total_books": 42,  # 模拟数据
            "total_duration_hours": 127.5,
            "supported_formats": list(self.supported_formats),
            "status": "online",
            "last_updated": datetime.now().isoformat()
        }


def main():
    """主函数 - 演示 Audiobookshelf 集成"""
    print("=== Audiobook Studio Audiobookshelf 集成演示 ===\n")

    # 配置 Audiobookshelf 连接
    config = AudiobookshelfConfig(
        api_url="http://localhost:8080/api",
        api_key="your_api_key_here",  # 在实际使用中应从环境变量或安全储存中读取
        library_id="main_library",
        supported_formats=["m4b", "mp3"],
        auto_convert=True,
        preferred_format="m4b"
    )

    # 创建集成器
    publisher = AudiobookshelfPublisher(config)

    print("🔧 配置 Audiobookshelf 连接:")
    print(f"   API 地址: {config.api_url}")
    print(f"   库 ID: {config.library_id}")
    print(f"   支持格式: {', '.join(config.supported_formats)}")
    print(f"   自动转换: {'✅ 是' if config.auto_convert else '❌ 否'}")

    print("\n" + "="*60)

    # 准备有声书元数据
    print("\n📚 准备有声书元数据...")
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
        cover_image_path=Path("./covers/saneti_cover.jpg")  # 假设存在
    )

    print(f"   标题: {metadata.title}")
    print(f"   作者: {metadata.author}")
    print(f"   朗读者: {metadata.narrator}")
    print(f"   描述: {metadata.description[:50]}...")

    print("\n" + "="*60)

    # 准备音频文件信息
    print("\n🔊 准备音频文件信息...")
    # 模拟一个实际的 M4B 文件
    audio_file_path = Path("./audiobooks/saneti_full.m4b")
    # 在实际使用中，这个文件 zou 是由之前的流程生成的

    # 为了演示，我们创建一个假的文件信息对象
    audio_file = AudiobookFile(
        file_path=audio_file_path,
        size_bytes=457283092,  # ~436 MB
        duration_seconds=21*60*60 + 45*60 + 30,  # 21小时45分30秒
        format="m4b",
        bitrate_kbps=64,
        checksum_md5="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",  # 假设的MD5
        chapters=[
            {
                "title": "第一章 文化大革命",
                "start": 0,
                "end": 1800  # 30分钟
            },
            {
                "title": "第二章 红岸基地",
                "start": 1800,
                "end": 5400  # 1.5小时
            },
            # 省略中间章节...
            {
                "title": "章节二十九  szerTranslator",
                "start": 75600,
                "end": 77400  # 最后30分钟
            }
        ]
    )

    print(f"   文件名: {audio_file.file_path.name}")
    print(f"   文件大小: {audio_file.size_bytes / (1024*1024):.1f} MB")
    print(f"   时长: {int(audio_file.duration_seconds//3600):02d}:{int((audio_file.duration_seconds%3600)//60):02d}:{int(audio_file.duration_seconds%60):02d}")
    print(f"   格式: {audio_file.format}")
    print(f"   比特率: {audio_file.bitrate_kbps} kbps")
    print(f"   章节数: {len(audio_file.chapters)}")

    print("\n" + "="*60)

    # 验证准备工作
    print("\n🔍 验证有声书信息...")
    valid, message, upload_data = publisher._prepare_audiobook(metadata, audio_file)
    if valid:
        print("   ✅ 有声书信息验证通过")
        print(f"   📊 准备上传的数据字段: {len(upload_data)} 项")
    else:
        print(f"   ❌ 验证失败: {message}")
        return

    print("\n" + "="*60)

    # 模拟发布到 Audiobookshelf
    print("\n🚀 发布到 Audiobookshelf...")
    success, message, response = publisher.publish_audiobook(metadata, audio_file)

    if success:
        print(f"   ✅ {message}")
        if response:
            print(f"   📖 书籍 ID: {response.get('book_id')}")
            print(f"   🆔 导入 ID: {response.get('import_id')}")
            if 'book' in response:
                book_info = response['book']
                print(f"   📅 添加时间: {book_info.get('addedAt')}")
    else:
        print(f"   ❌ {message}")
        if response and response.get('is_duplicate'):
            print(f"   💡 提示: 这可能是一本重复的书籍，您可以选择更新现有条目或跳过")

    print("\n" + "="*60)

    # 显示库状态
    print("\n📊 Audiobookshelf 库状态:")
    status = publisher.get_library_status()
    print(f"   库 ID: {status['library_id']}")
    print(f"   图书总数: {status['total_books']} 本")
    print(f"   时长总计: {status['total_duration_hours']} 小时")
    print(f"   支持格式: {', '.join(status['supported_formats'])}")
    print(f"   服务器状态: {status['status']}")
    print(f"   最后更新: {status['last_updated']}")

    print("\n" + "="*60)
    print("🎉 Audiobookshelf 集成演示完成")
    print("="*60)


if __name__ == "__main__":
    main()