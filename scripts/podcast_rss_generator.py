#!/usr/bin/env python3
"""
Audiobook Studio — Podcast RSS Feed 生成器
========================================
实现将有声书章节转换为 Podcast RSS Feed（每章一集）。
"""

import json
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET


@dataclass
class PodcastEpisode:
    """Podcast 节目（对应有声书的一章）"""
    title: str
    description: str
    audio_file_path: Path
    duration_seconds: int
    pub_date: datetime
    guid: str = field(init=False)
    enclosure_length: int = 0
    enclosure_type: str = "audio/mpeg"
    # 可选字段
    episode_type: str = "full"  # full, trailer, bonus
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    explicit: bool = False

    def __post_init__(self):
        # 生成基于文件内容的GUID
        self.guid = self._generate_guid()

    def _generate_guid(self) -> str:
        """基于音频文件生成唯一标识符"""
        try:
            # 如果文件存在，基于文件内容和修改时间生成哈希
            if self.audio_file_path.exists():
                stat = self.audio_file_path.stat()
                hash_input = f"{self.audio_file_path}:{stat.st_size}:{stat.st_mtime}"
                return hashlib.sha256(hash_input.encode()).hexdigest()
            else:
                # 如果文件不存在，基于路径和标题生成
                hash_input = f"{self.audio_file_path}:{self.title}:{self.pub_date.isoformat()}"
                return hashlib.sha256(hash_input.encode()).hexdigest()
        except Exception:
            # 后备方案：基于标题和时间
            hash_input = f"{self.title}:{self.pub_date.isoformat()}"
            return hashlib.sha256(hash_input.encode()).hexdigest()


@dataclass
class PodcastFeed:
    """Podcast RSS Feed"""
    title: str
    description: str
    link: str  # 网站 URL
    language: str = "zh-CN"
    copyright: str = f"© {datetime.now().year} Audiobook Studio"
    author: str = ""
    owner_name: str = ""
    owner_email: str = ""
    image_url: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    explicit: bool = False
    # iTunes 特定字段
    itunes_author: str = ""
    itunes_owner_name: str = ""
    itunes_owner_email: str = ""
    itunes_explicit: str = "no"
    itunes_categories: List[Tuple[str, Optional[str]]] = field(default_factory=list)

    episodes: List[PodcastEpisode] = field(default_factory=list)
    last_build_date: datetime = field(default_factory=datetime.now)
    generator: str = "Audiobook Studio Podcast Generator"


class PodcastRSSGenerator:
    """Podcast RSS Feed 生成器"""

    def __init__(self, feed: PodcastFeed):
        self.feed = feed

    def add_episode(self, episode: PodcastEpisode):
        """添加一个节目到Feed"""
        self.feed.episodes.append(episode)
        # 按发布日期倒序排列（最新的在前）
        self.feed.episodes.sort(key=lambda e: e.pub_date, reverse=True)
        # 重新分配 episode_number（如果没有手动设置的话）
        self._reassign_episode_numbers()

    def _reassign_episode_numbers(self):
        """重新分配 épisode 编号（基于发布顺序）"""
        # 只为没有手动设置编号的 épisode 重新分配
        episodes_without_number = [ep for ep in self.feed.episodes if ep.episode_number is None]
        for i, episode in enumerate(episodes_without_number, 1):
            episode.episode_number = len(self.feed.episodes) - len(episodes_without_number) + i

    def generate_rss_xml(self) -> str:
        """生成 RSS XML 内容"""
        # 创建根元素
        rss = ET.Element("rss")
        rss.set("version", "2.0")
        rss.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        rss.set("xmlns:content", "http://purl.org/rss/1.0/modules/content/")
        rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

        # 创建channel元素
        channel = ET.SubElement(rss, "channel")

        # 添加基本feed信息
        self._add_basic_channel_elements(channel)
        self._add_itunes_channel_elements(channel)
        self._add_atom_self_link(channel)

        # 添加节目
        for episode in self.feed.episodes:
            self._add_episode_element(channel, episode)

        # 更新最后构建时间
        self.feed.last_build_date = datetime.now()

        # 生成XML字符串
        rough_string = ET.tostring(rss, encoding='unicode')
        # 为了美观，我们可以使用minidom来格式化，但这里保持简单
        return rough_string

    def _add_basic_channel_elements(self, channel: ET.Element):
        """添加基本的channel元素"""
        ET.SubElement(channel, "title").text = self.feed.title
        ET.SubElement(channel, "description").text = self.feed.description
        ET.SubElement(channel, "link").text = self.feed.link
        ET.SubElement(channel, "language").text = self.feed.language
        ET.SubElement(channel, "copyright").text = self.feed.copyright

        if self.feed.author:
            ET.SubElement(channel, "author").text = self.feed.author

        if self.feed.owner_name and self.feed.owner_email:
            ET.SubElement(channel, "managingEditor").text = f"{self.feed.owner_email} ({self.feed.owner_name})"
            ET.SubElement(channel, "webMaster").text = f"{self.feed.owner_email} ({self.feed.owner_name})"

        ET.SubElement(channel, "lastBuildDate").text = self.feed.last_build_date.strftime("%a, %d %b %Y %H:%M:%S %Z")
        ET.SubElement(channel, "generator").text = self.feed.generator

        # 添加分类
        for category in self.feed.categories:
            ET.SubElement(channel, "category").text = category

        # 添加图片
        if self.feed.image_url:
            image_elem = ET.SubElement(channel, "image")
            ET.SubElement(image_elem, "url").text = self.feed.image_url
            ET.SubElement(image_elem, "title").text = self.feed.title
            ET.SubElement(image_elem, "link").text = self.feed.link

    def _add_itunes_channel_elements(self, channel: ET.Element):
        """添加iTunes特定的channel元素"""
        if self.feed.itunes_author:
            ET.SubElement(channel, "itunes:author").text = self.feed.itunes_author

        if self.feed.itunes_owner_name and self.feed.itunes_owner_email:
            owner_elem = ET.SubElement(channel, "itunes:owner")
            ET.SubElement(owner_elem, "itunes:name").text = self.feed.itunes_owner_name
            ET.SubElement(owner_elem, "itunes:email").text = self.feed.itunes_owner_email

        ET.SubElement(channel, "itunes:explicit").text = self.feed.itunes_explicit

        if self.feed.itunes_categories:
            for category, subcategory in self.feed.itunes_categories:
                cat_elem = ET.SubElement(channel, "itunes:category")
                cat_elem.set("text", category)
                if subcategory:
                    subcat_elem = ET.SubElement(cat_elem, "itunes:category")
                    subcat_elem.set("text", subcategory)

    def _add_atom_self_link(self, channel: ET.Element):
        """添加Atom自链接（用于播客客户端检测更新）"""
        # 实际应用中，这个链接 zou 指向此RSS feed本身的URL
        atom_link = ET.SubElement(channel, "atom:link")
        atom_link.set("rel", "self")
        atom_link.set("type", "application/rss+xml")
        atom_link.set("href", self.feed.link)  # 简化处理，实际应为feed的URL

    def _add_episode_element(self, channel: ET.Element, episode: PodcastEpisode):
        """添加一个节目元素"""
        item = ET.SubElement(channel, "item")

        # 基本元素
        ET.SubElement(item, "title").text = episode.title
        ET.SubElement(item, "description").text = episode.description
        ET.SubElement(item, "guid").text = episode.guid
        ET.SubElement(item, "guid").set("isPermaLink", "false")
        ET.SubElement(item, "pubDate").text = episode.pub_date.strftime("%a, %d %b %Y %H:%M:%S %Z")

        # Enclosure (音频文件)
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", str(episode.audio_file_path))  # 在实际应用中，这 zou 是可访问的URL
        enclosure.set("length", str(enclosure.enclosure_length or episode.audio_file_path.stat().st_size if episode.audio_file_path.exists() else 0))
        enclosure.set("type", episode.enclosure_type)

        # 可选元素
        if episode.episode_number is not None:
            ET.SubElement(item, "itunes:episode").text = str(episode.episode_number)
        if episode.season_number is not None:
            ET.SubElement(item, "itunes:season").text = str(episode.season_number)
        ET.SubElement(item, "itunes:episodeType").text = episode.episode_type
        ET.SubElement(item, "itunes:explicit").text = "yes" if episode.explicit else "no"

    def save_to_file(self, file_path: Path) -> Tuple[bool, str]:
        """将RSS Feed保存到文件"""
        try:
            # 确保目录存在
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # 生成XML
            xml_content = self.generate_rss_xml()

            # 美化输出（添加声明和缩进）
            formatted_xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_content}'

            # 写入文件
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(formatted_xml)

            return True, f"RSS Feed已保存到: {file_path}"
        except Exception as e:
            return False, f"保存RSS Feed失败: {str(e)}"

    def validate_feed(self) -> Tuple[bool, List[str]]:
        """验证Feed的完整性"""
        errors = []

        # 检查必填字段
        if not self.feed.title.strip():
            errors.append("Feed标题不能为空")
        if not self.feed.description.strip():
            errors.append("Feed描述不能为空")
        if not self.feed.link.strip():
            errors.append("Feed链接不能为空")

        # 检查节目
        if not self.feed.episodes:
            errors.append("Feed必须包含至少一个节目")
        else:
            for i, episode in enumerate(self.feed.episodes):
                if not episode.title.strip():
                    errors.append(f"节目 {i+1} 标题不能为空")
                if not episode.description.strip():
                    errors.append(f"节目 {i+1} 描述不能为空")
                if not episode.audio_file_path:
                    errors.append(f"节目 {i+1} 音频文件路径不能为空")
                # 检查文件是否存在（警告而不是错误，因为文件可能尚未生成）
                if not episode.audio_file_path.exists():
                    # 这只是一个警告，不添加到errors中
                    pass

        return len(errors) == 0, errors


def main():
    """主函数 - 演示 Podcast RSS Feed 生成"""
    print("=== Audiobook Studio Podcast RSS Feed 生成演示 ===\n")

    # 创建Podcast Feed
    print("📻 创建Podcast Feed...")
    feed = PodcastFeed(
        title="三体有声书",
        description="刘慈欣科幻巨作《三体》有声书版本，每章节对应一集节目。",
        link="https://audiobookstudio.example.com/podcasts/saneti",
        language="zh-CN",
        author="Audiobook Studio",
        owner_name="Audiobook Studio Team",
        owner_email="podcast@audiobookstudio.example.com",
        image_url="https://audiobookstudio.example.com/covers/saneti_podcast.jpg",
        categories=["科幻", "文学", "有声书"],
        explicit=False,
        itunes_author="Audiobook Studio",
        itunes_owner_name="Audiobook Studio Team",
        itunes_owner_email="podcast@audiobookstudio.example.com",
        itunes_explicit="no",
        itunes_categories=[
            ("Arts", "Books"),
            ("Technology", "Podcasting"),
            ("Society & Culture", "Philosophy")
        ]
    )

    print(f"   标题: {feed.title}")
    print(f"   描述: {feed.description}")
    print(f"   链接: {feed.link}")
    print(f"   语言: {feed.language}")

    print("\n" + "="*60)

    # 创建生成器
    generator = PodcastRSSGenerator(feed)

    # 模拟有声书章节（对应每章一集）
    print("\n📖 添加有声书章节作为Podcast节目...")

    # 假设我们有一个有声书，包含若干章节
    chapters_data = [
        {
            "title": "第一章 文化大革命的序曲",
            "description": "在这个动荡的时代，一个秘密的军事项目《红岸工程》正在酝酿之中。",
            "audio_file": Path("./episodes/chapter_01_cultural_revolution.mp3"),
            "duration": 1800,  # 30分钟
            "days_offset": 0
        },
        {
            "title": "第二章 红岸基地的建立",
            "description": "叶文洁在红岸基地经历了人生中最黑暗的时刻，却意外打开了通往宇宙的窗口。",
            "audio_file": Path("./episodes/chapter_02_red_coast_base.mp3"),
            "duration": 2100,  # 35分钟
            "days_offset": 1
        },
        {
            "title": "第三章 三体世界的初次接触",
            "description": "叶文洁向太空发送了第一条信息，并在遥远的三体世界得到了回应。",
            "audio_file": Path("./episodes/chapter_03_third_contact.mp3"),
            "duration": 2400,  # 40分钟
            "days_offset": 2
        },
        {
            "title": "第四章 地球三体运动的成立",
            "description": "汪淼 découvertes 了一个神秘的组织——地球三体运动，并开始了他的调查。",
            "audio_file": Path("./episodes/chapter_04_eto.mp3"),
            "duration": 1950,  # 32.5分钟
            "days_offset": 3
        },
        {
            "title": "第五章 三体游戏与现实的交汇",
            "description": "汪淼进入了《三体》游戏，在地球上和虚拟世界之间寻找平衡。",
            "audio_file": Path("./episodes/chapter_05_the_game.mp3"),
            "duration": 2200,  # 36分40秒
            "days_offset": 4
        }
    ]

    base_date = datetime.now() - timedelta(days=len(chapters_data))

    for i, chapter_data in enumerate(chapters_data):
        # 计算发布日期（每天一集）
        pub_date = base_date + timedelta(days=chapter_data["days_offset"])

        episode = PodcastEpisode(
            title=chapter_data["title"],
            description=chapter_data["description"],
            audio_file_path=chapter_data["audio_file"],
            duration_seconds=chapter_data["duration"],
            pub_date=pub_date,
            episode_number=i+1,  # 明确设置集数
            season_number=1,     # 第一季
            explicit=False
        )

        generator.add_episode(episode)
        print(f"   第{i+1}集: {chapter_data['title']}")
        print(f"      时长: {chapter_data['duration']//60}分{chapter_data['duration']%60:02d}秒")
        print(f"      发布日期: {pub_date.strftime('%Y-%m-%d')}")

    print("\n" + "="*60)

    # 验证Feed
    print("\n🔍 验证Podcast Feed...")
    is_valid, errors = generator.validate_feed()
    if is_valid:
        print("   ✅ Feed验证通过")
    else:
        print("   ❌ Feed验证失败:")
        for error in errors:
            print(f"      - {error}")
        # 继续演示，即使验证失败

    # 生成并保存RSS Feed
    print("\n📄 生成RSS Feed XML...")
    rss_xml = generator.generate_rss_xml()

    # 显示前几行以演示
    xml_lines = rss_xml.split('\n')
    print("   RSS Feed 前10行:")
    for line in xml_lines[:10]:
        print(f"      {line}")
    if len(xml_lines) > 10:
        print("      ...")

    # 保存到文件
    output_path = Path("./feeds/saneti_podcast.rss")
    success, message = generator.save_to_file(output_path)

    if success:
        print(f"\n   ✅ {message}")
        # 显示文件大小
        if output_path.exists():
            size_kb = output_path.stat().st_size / 1024
            print(f"   📁 文件大小: {size_kb:.1f} KB")
    else:
        print(f"\n   ❌ {message}")

    print("\n" + "="*60)

    # 显示统计信息
    print("\n📈 Feed统计信息:")
    print(f"   节目总数: {len(generator.feed.episodes)} 集")
    total_duration = sum(ep.duration_seconds for ep in generator.feed.episodes)
    print(f"   时长总计: {total_duration//3600:02d}:{(total_duration%3600)//60:02d}:{total_duration%60:02d}")
    print(f"   首次发布: {min(ep.pub_date for ep in generator.feed.episodes).strftime('%Y-%m-%d')}")
    print(f"   最新发布: {max(ep.pub_date for ep in generator.feed.episodes).strftime('%Y-%m-%d')}")

    print("\n" + "="*60)
    print("🎉 Podcast RSS Feed 生成演示完成")
    print("="*60)


if __name__ == "__main__":
    main()