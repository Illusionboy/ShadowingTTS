#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TTS Agent 字幕生成集成示例

本文件展示了如何在 TTS 项目中调用 JaVideoSrtGenAgent 的字幕生成接口。
可以直接复制到 TTS 项目中使用。
"""

import json
import sys
import time
import logging
from pathlib import Path
from typing import Optional, Tuple

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(name)s] - %(message)s"
)
logger = logging.getLogger(__name__)


class SubtitleGenerator:
    """
    字幕生成器 - 为 TTS 项目提供统一的字幕接口
    """
    
    def __init__(self, ja_video_agent_dir: str, config_path: Optional[str] = None):
        """
        初始化字幕生成器
        
        Args:
            ja_video_agent_dir: JaVideoSrtGenAgent 项目的根目录路径
            config_path: config.json 的路径（默认为 ja_video_agent_dir/config.json）
        """
        self.ja_video_agent_dir = Path(ja_video_agent_dir).resolve()
        
        # 将 JaVideoSrtGenAgent 加入 sys.path
        if str(self.ja_video_agent_dir) not in sys.path:
            sys.path.insert(0, str(self.ja_video_agent_dir))
        
        # 加载配置
        if config_path is None:
            config_path = self.ja_video_agent_dir / "config.json"
        
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        self.config = self._load_config()
        
        # 导入 JaVideoSrtGenAgent 的 API
        try:
            from master_multiprcs import (
                enqueue_media_for_subtitle,
                start_pipeline
            )
            self.enqueue_media_for_subtitle = enqueue_media_for_subtitle
            self.start_pipeline = start_pipeline
            self._pipeline_started = False
        except ImportError as e:
            raise ImportError(
                f"无法导入 master_multiprcs，请检查 {self.ja_video_agent_dir} 是否为有效的 JaVideoSrtGenAgent 目录"
            ) from e
        
        logger.info(f"✅ 字幕生成器初始化成功，项目路径: {self.ja_video_agent_dir}")
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"📋 配置已加载: {self.config_path}")
            return config
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}") from e
    
    def initialize(self):
        """
        启动字幕流水线（仅需调用一次，通常在 TTS Agent 启动时）
        """
        if self._pipeline_started:
            logger.warning("⚠️ 流水线已启动，无需重复初始化")
            return
        
        try:
            self.start_pipeline(self.config)
            self._pipeline_started = True
            logger.info("🚀 字幕转写和翻译流水线已启动")
        except Exception as e:
            logger.error(f"❌ 启动流水线失败: {e}")
            raise
    
    def generate_subtitle(
        self,
        media_path: str,
        lang: str = "ja",
        bilingual: bool = True,
        wait: bool = False,
        timeout: int = 600
    ) -> Optional[Path]:
        """
        生成字幕
        
        Args:
            media_path: 音视频文件路径（绝对或相对）
            lang: 识别语言（默认 "ja"）
            bilingual: True 生成双语字幕，False 仅生成日文
            wait: 是否阻塞等待字幕生成完成（默认 False - 异步）
            timeout: 最长等待时间（秒，仅当 wait=True 时有效）
        
        Returns:
            字幕文件路径，或 None（如果生成失败）
        """
        if not self._pipeline_started:
            logger.warning("⚠️ 流水线未启动，自动调用 initialize()...")
            self.initialize()
        
        # 验证媒体文件存在
        media_path = Path(media_path).resolve()
        if not media_path.exists():
            logger.error(f"❌ 媒体文件不存在: {media_path}")
            return None
        
        logger.info(f"📤 投递字幕任务: {media_path.name} (lang={lang}, bilingual={bilingual})")
        
        try:
            # 调用 API 投递任务
            queued_path = self.enqueue_media_for_subtitle(
                media_path=str(media_path),
                config=self.config,
                lang=lang,
                no_trans=not bilingual  # False -> 双语，True -> 单语
            )
            logger.info(f"✅ 任务已投递，排队路径: {queued_path}")
            
            if wait:
                return self._wait_for_subtitle(
                    media_path=Path(queued_path),
                    bilingual=bilingual,
                    timeout=timeout
                )
            else:
                # 异步模式，返回预期的输出路径
                return self._get_expected_output_path(media_path, bilingual)
        
        except FileNotFoundError as e:
            logger.error(f"❌ 媒体文件错误: {e}")
            return None
        except ValueError as e:
            logger.error(f"❌ 不支持的格式: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ 投递失败: {e}")
            return None
    
    def _get_expected_output_path(self, media_path: Path, bilingual: bool) -> Path:
        """预测输出文件路径"""
        out_dir = Path(self.config.get("out_dir", "./exports"))
        suffix = "_bi" if bilingual else ""
        return out_dir / f"{media_path.stem}{suffix}.srt"
    
    def _wait_for_subtitle(
        self,
        media_path: Path,
        bilingual: bool,
        timeout: int
    ) -> Optional[Path]:
        """
        阻塞等待字幕生成完成
        
        Args:
            media_path: 媒体文件路径
            bilingual: 是否为双语字幕
            timeout: 最长等待时间（秒）
        
        Returns:
            字幕文件路径，或 None（超时）
        """
        expected_path = self._get_expected_output_path(media_path, bilingual)
        
        logger.info(f"⏳ 等待字幕生成... (最多 {timeout} 秒)")
        start = time.time()
        
        while time.time() - start < timeout:
            if expected_path.exists():
                elapsed = time.time() - start
                logger.info(f"✅ 字幕已生成: {expected_path} (耗时 {elapsed:.1f} 秒)")
                return expected_path
            
            time.sleep(2)  # 每 2 秒检查一次
        
        logger.warning(f"⚠️ 字幕生成超时 ({timeout} 秒): {expected_path}")
        return None
    
    def read_subtitle_content(self, srt_path: str) -> Optional[str]:
        """
        读取字幕文件内容
        
        Args:
            srt_path: 字幕文件路径
        
        Returns:
            字幕文本内容，或 None（文件不存在）
        """
        srt_file = Path(srt_path)
        if not srt_file.exists():
            logger.error(f"❌ 字幕文件不存在: {srt_path}")
            return None
        
        try:
            with open(srt_file, "r", encoding="utf-8") as f:
                content = f.read()
            logger.info(f"📖 已读取字幕: {srt_file.name}")
            return content
        except Exception as e:
            logger.error(f"❌ 读取字幕失败: {e}")
            return None


# ============================================================================
# 使用示例
# ============================================================================

def example_basic_usage():
    """示例 1：基础使用"""
    print("\n" + "="*60)
    print("示例 1: 基础用法 - 生成双语字幕（异步）")
    print("="*60)
    
    # 初始化生成器
    generator = SubtitleGenerator(
        ja_video_agent_dir="../JaVideoSrtGenAgent",  # 根据实际路径修改
        # config_path="../JaVideoSrtGenAgent/config.json"  # 可选，默认自动查找
    )
    
    # 启动流水线（仅需一次）
    generator.initialize()
    
    # 投递字幕任务（异步）
    srt_path = generator.generate_subtitle(
        media_path="./generated_audio.wav",
        lang="ja",
        bilingual=True,
        wait=False  # 异步模式，立即返回
    )
    
    if srt_path:
        print(f"\n预期输出路径: {srt_path}")
        print("字幕生成中，请稍候...\n")


def example_sync_wait():
    """示例 2：同步等待生成完成"""
    print("\n" + "="*60)
    print("示例 2: 同步等待 - 等待字幕生成完成")
    print("="*60)
    
    generator = SubtitleGenerator(
        ja_video_agent_dir="../JaVideoSrtGenAgent"
    )
    generator.initialize()
    
    # 投递任务并等待完成
    srt_path = generator.generate_subtitle(
        media_path="./generated_audio.wav",
        lang="ja",
        bilingual=True,
        wait=True,      # 同步等待
        timeout=600     # 最多等 10 分钟
    )
    
    if srt_path:
        content = generator.read_subtitle_content(str(srt_path))
        if content:
            print(f"\n字幕内容:\n{content[:500]}...")  # 仅展示前 500 字
    else:
        print("\n❌ 字幕生成失败或超时")


def example_japanese_only():
    """示例 3：仅生成日文字幕（跳过翻译）"""
    print("\n" + "="*60)
    print("示例 3: 仅生成日文字幕（跳过翻译）")
    print("="*60)
    
    generator = SubtitleGenerator(
        ja_video_agent_dir="../JaVideoSrtGenAgent"
    )
    generator.initialize()
    
    # bilingual=False 表示仅保存单语（日文）字幕
    srt_path = generator.generate_subtitle(
        media_path="./generated_audio.wav",
        lang="ja",
        bilingual=False,  # 跳过翻译
        wait=False
    )
    
    if srt_path:
        print(f"单语字幕将保存至: {srt_path}")


def example_different_language():
    """示例 4：识别不同语言"""
    print("\n" + "="*60)
    print("示例 4: 识别英文并翻译成中文")
    print("="*60)

    generator = SubtitleGenerator(
        ja_video_agent_dir="../JaVideoSrtGenAgent"
    )
    generator.initialize()

    # 改为识别英文
    srt_path = generator.generate_subtitle(
        media_path="./english_audio.wav",
        lang="en",        # 改为英文
        bilingual=True,
        wait=False
    )

    if srt_path:
        print(f"英文+中文字幕将保存至: {srt_path}")


def example_watch_dir_with_lang_suffix():
    """示例 5：watch_dir 模式 - 通过文件名后缀指定语言（推荐集成方式）"""
    print("\n" + "="*60)
    print("示例 5: watch_dir 模式 - 文件名 lang 后缀自动投递")
    print("="*60 + "\n")

    import shutil
    import json

    config = json.load(open("../JaVideoSrtGenAgent/config.json"))
    watch_dir = Path(config["watch_dir"])
    out_dir = Path(config["out_dir"])

    watch_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    def submit_with_lang(audio_path: str, lang: str) -> Path:
        """将音频以 lang 后缀格式投递到 watch_dir。

        命名规则：{原始名}.{lang代码}.{扩展名}
          output.wav + lang=ja → watch_dir/output.ja.wav
          lecture.mp3 + lang=en → watch_dir/lecture.en.mp3

        VideoSRT Agent 会自动识别后缀、剥离 lang 标签，
        最终输出 output_bi.srt 和 lecture_bi.srt（不含 lang 标签）。
        """
        src = Path(audio_path)
        dest_name = f"{src.stem}.{lang}{src.suffix}"
        dest = watch_dir / dest_name
        shutil.copy2(src, dest)
        logger.info(f"✅ 已投递: {dest} (lang={lang})")
        return dest

    # TTS 生成的音频列表（每条带有已知语言）
    tasks = [
        ("./generated_ja.wav", "ja"),   # 日文音频
        ("./generated_en.mp3", "en"),   # 英文音频
        ("./generated_zh.m4a", "zh"),   # 中文音频
    ]

    for audio_path, lang in tasks:
        if not Path(audio_path).exists():
            print(f"[跳过] 文件不存在: {audio_path}")
            continue
        submit_with_lang(audio_path, lang)

    print("\n所有文件已投递，字幕将依次出现在:")
    print(f"  {out_dir}/generated_ja_bi.srt")
    print(f"  {out_dir}/generated_en_bi.srt")
    print(f"  {out_dir}/generated_zh_bi.srt")


def example_tts_integration():
    """示例 6：集成到 TTS Agent 的推荐方式"""
    print("\n" + "="*60)
    print("示例 6: TTS Agent 集成推荐方式")
    print("="*60 + "\n")
    
    # 在 TTS Agent 的初始化函数中
    class TTSAgentWithSubtitle:
        def __init__(self, subtitle_config):
            self.subtitle_gen = SubtitleGenerator(
                ja_video_agent_dir=subtitle_config["agent_dir"],
                config_path=subtitle_config.get("config_path")
            )
            # 初始化字幕流水线
            self.subtitle_gen.initialize()
        
        def process_tts(self, text: str, audio_output_path: str) -> Tuple[str, Optional[str]]:
            """
            TTS 处理流程 + 自动字幕生成
            
            Args:
                text: 输入文本
                audio_output_path: 生成的音频文件路径
            
            Returns:
                (音频路径, 字幕路径)
            """
            # 1. 执行 TTS（生成音频）
            print(f"[TTS] 处理文本: {text[:50]}...")
            # ... 您的 TTS 逻辑 ...
            print(f"[TTS] 音频已生成: {audio_output_path}")
            
            # 2. 自动生成双语字幕
            print("[字幕] 生成双语字幕...")
            srt_path = self.subtitle_gen.generate_subtitle(
                media_path=audio_output_path,
                lang="ja",
                bilingual=True,
                wait=True,
                timeout=600
            )
            
            if srt_path:
                print(f"[字幕] 完成: {srt_path}")
            else:
                print("[字幕] 失败")
            
            return audio_output_path, srt_path
    
    # 使用示例
    tts_agent = TTSAgentWithSubtitle({
        "agent_dir": "../JaVideoSrtGenAgent",
        # "config_path": "..."  # 可选
    })
    
    audio_path, srt_path = tts_agent.process_tts(
        text="こんにちは、これはテスト音声です。",
        audio_output_path="./output.wav"
    )
    
    print(f"\n最终输出:")
    print(f"  音频: {audio_path}")
    print(f"  字幕: {srt_path}")


if __name__ == "__main__":
    # 运行示例（取消注释以测试）

    # example_basic_usage()           # 示例 1: 异步投递双语字幕
    # example_sync_wait()             # 示例 2: 同步等待字幕完成
    # example_japanese_only()         # 示例 3: 仅单语字幕（跳过翻译）
    # example_different_language()    # 示例 4: 英文识别
    # example_watch_dir_with_lang_suffix()  # 示例 5: watch_dir + lang 后缀（推荐）
    # example_tts_integration()       # 示例 6: 完整 TTS Agent 集成

    print("\n提示：这是一个集成示例文件，请根据实际需求修改路径和调用方式。")
    print("详见 SUBTITLE_INTERFACE.md 了解完整的 API 文档。")
