"""Podcast RSS Feed Generation - 自动生成RSS播客Feed.

实现根据音频章节自动生成标准RSS 2.0格式播客Feed，
每章节对应一集播客，支持订阅和播放。
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from ..models.audio_segment import AudioSegment
from ..models.book import Book
from ..models.chapter import Chapter

logger = logging.getLogger(__name__)


class RssFeedGenerator:
    """生成符合RSS 2.0标准的播客Feed."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        初始化RSS Feed生成器.

        Args:
            base_url: 播客文件和封面图片的基础URL
        """
        self.base_url = base_url.rstrip("/")
        logger.info(f"RssFeedGenerator initialized with base_url: {self.base_url}")

    def generate_rss_feed(
        self,
        book: Book,
        chapters: List[Chapter],
        audio_segments_by_chapter: Dict[int, List[AudioSegment]],
        cover_image_url: Optional[str] = None,
    ) -> str:
        """
        为有声书生成RSS播客Feed.

        Args:
            book: 有声书元数据
            chapters: 章节列表
            audio_segments_by_chapter: 按章节分组的音频片段字典 {chapter_id: [segments]}
            cover_image_url: 封面图片URL（可选）

        Returns:
            RSS 2.0格式的XML字符串
        """
        logger.info(f"Generating RSS feed for book: {book.title}")

        # 创建RSS根元素
        rss = ET.Element("rss", version="2.0")
        rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")

        channel = ET.SubElement(rss, "channel")

        # 基本频道信息
        title_elem = ET.SubElement(channel, "title")
        title_elem.text = f"{book.title} - 有声书"

        link_elem = ET.SubElement(channel, "link")
        link_elem.text = self.base_url

        description_elem = ET.SubElement(channel, "description")
        description_elem.text = (
            f"由Audiobook Studio自动生成的有声书：《{book.title}》"
            f" 作者：{book.author or '未知'}"
        )

        language_elem = ET.SubElement(channel, "language")
        language_elem.text = "zh-CN"

        # 作者信息
        author_elem = ET.SubElement(channel, "author")
        author_elem.text = book.author or "未知作者"

        # 版权信息
        copyright_elem = ET.SubElement(channel, "copyright")
        copyright_elem.text = f"© {datetime.now().year} {book.author or '未知作者'}"

        # 封面图片
        if cover_image_url:
            image_elem = ET.SubElement(channel, "image")
            url_elem = ET.SubElement(image_elem, "url")
            url_elem.text = cover_image_url
            title_elem_img = ET.SubElement(image_elem, "title")
            title_elem_img.text = f"{book.title} 封面"
            link_elem_img = ET.SubElement(image_elem, "link")
            link_elem_img.text = self.base_url

        # iTunes特定标签
        itunes_author = ET.SubElement(channel, "itunes:author")
        itunes_author.text = book.author or "未知作者"

        itunes_summary = ET.SubElement(channel, "itunes:summary")
        itunes_summary.text = (
            f"由Audiobook Studio自动生成的有声书：《{book.title}》"
            f" 共{len(chapters)}章，采用先进的AI技术进行情感分析和角色配音。"
        )

        itunes_owner = ET.SubElement(channel, "itunes:owner")
        itunes_name = ET.SubElement(itunes_owner, "itunes:name")
        itunes_name.text = "Audiobook Studio"
        itunes_email = ET.SubElement(itunes_owner, "itunes:email")
        itunes_email.text = "noreply@audiobook.studio"

        itunes_explicit = ET.SubElement(channel, "itunes:explicit")
        itunes_explicit.text = "no"

        itunes_category = ET.SubElement(channel, "itunes:category")
        itunes_category.set("text", "Arts")
        itunes_subcategory = ET.SubElement(itunes_category, "itunes:category")
        itunes_subcategory.set("text", "Books")

        # 生成每章节作为一集播客
        for chapter in chapters:
            chapter_id = chapter.id
            audio_segments = audio_segments_by_chapter.get(chapter_id, [])

            if not audio_segments:
                logger.warning(f"Chapter {chapter_id} has no audio segments, skipping")
                continue

            # 计算章节总时长
            total_duration_ms = sum(
                seg.duration_ms for seg in audio_segments if seg.duration_ms
            )
            total_duration_seconds = total_duration_ms // 1000
            hours = total_duration_seconds // 3600
            minutes = (total_duration_seconds % 3600) // 60
            seconds = total_duration_seconds % 60
            duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # 创建播客条目
            item_elem = ET.SubElement(channel, "item")

            item_title = ET.SubElement(item_elem, "title")
            item_title.text = f"第{chapter_id}章 {chapter.title}"

            item_description = ET.SubElement(item_elem, "description")
            item_description.text = (
                f"{chapter.summary or chapter.title}\n\n"
                f"本章包含{len(audio_segments)}个音频片段，"
                f"总时长{duration_str}。"
            )

            # 添加章节内容（如果有的话）
            if hasattr(chapter, "content") and chapter.content:
                content_elem = ET.SubElement(item_elem, "content:encoded")
                content_elem.text = f"<![CDATA[{chapter.content}]]>"

            item_pub_date = ET.SubElement(item_elem, "pubDate")
            # 使用书的创建时间或当前时间
            pub_date = getattr(book, "created_at", datetime.now())
            if isinstance(pub_date, datetime):
                item_pub_date.text = pub_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
            else:
                item_pub_date.text = datetime.now().strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )

            item_guid = ET.SubElement(item_elem, "guid")
            item_guid.text = f"{book.id}-chapter-{chapter_id}"
            item_guid.set("isPermaLink", "false")

            # 音频文件URL（这里我们使用章节ID作为文件名的示例）
            audio_filename = f"book_{book.id}_chapter_{chapter_id}.m4b"
            enclosure_url = urljoin(self.base_url + "/", f"audio/{audio_filename}")
            item_enclosure = ET.SubElement(item_elem, "enclosure")
            item_enclosure.set("url", enclosure_url)
            item_enclosure.set("type", "audio/mp4")
            item_enclosure.set("length", str(total_duration_ms * 2))  # 估算文件大小

            item_duration = ET.SubElement(item_elem, "itunes:duration")
            item_duration.text = duration_str

            # 章节号
            item_episode = ET.SubElement(item_elem, "itunes:episode")
            item_episode.text = str(chapter_id)

            item_episode_type = ET.SubElement(item_elem, "itunes:episodeType")
            item_episode_type.text = "full"

        # 生成XML字符串
        xml_str = ET.tostring(rss, encoding="unicode", method="xml")
        # 添加XML声明
        rss_output = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}'

        logger.info(f"RSS feed generated successfully for book {book.title}")
        return rss_output

    def save_rss_feed(
        self,
        rss_content: str,
        file_path: str,
    ) -> bool:
        """
        保存RSS Feed到文件.

        Args:
            rss_content: RSS XML内容
            file_path: 保存路径

        Returns:
            保存是否成功
        """
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(rss_content)
            logger.info(f"RSS feed saved to: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save RSS feed to {file_path}: {e}")
            return False
