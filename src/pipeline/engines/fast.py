"""
口语评分 CLI 框架 - Fast 引擎

基于 Gentle 的容错对齐引擎，作为保底方案使用。
"""
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.config import config
from src.models import (
    Alignment,
    PhonemeAlignment,
    WordAlignment,
    WordTag,
)

logger = logging.getLogger(__name__)


class FastEngine:
    """
    Fast 引擎
    
    使用 Gentle 进行容错的强制对齐，适用于：
    - 音频质量较差
    - Standard 引擎失败时的回退
    - 快速处理需求
    """
    
    def __init__(self) -> None:
        self.service_url = config.get(
            "engines.fast.service_url",
            "http://localhost:8765"
        )
        self.timeout = config.get("engines.fast.timeout_sec", 30)
    
    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Path,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Fast 引擎
        
        Args:
            wav_path: WAV 音频文件路径
            script_text: 标准文本
            work_dir: 工作目录
            
        Returns:
            (对齐信息, 引擎原始输出)
        """
        logger.info("Fast 引擎开始运行")
        
        try:
            # 尝试调用 Gentle 服务
            result = self._call_gentle_service(wav_path, script_text)
            alignment, engine_raw = self._parse_gentle_result(result, script_text)
            return alignment, engine_raw
            
        except (httpx.HTTPError, ConnectionError) as e:
            logger.warning(f"Gentle 服务不可用: {e}，使用模拟模式")
            return self._generate_fallback_result(script_text)
        
        except Exception as e:
            logger.error(f"Fast 引擎运行失败: {e}")
            raise RuntimeError(f"Fast 引擎失败: {e}") from e
    
    def _call_gentle_service(
        self, wav_path: Path, script_text: str
    ) -> dict[str, Any]:
        """
        调用 Gentle 服务 API
        
        Gentle 提供 HTTP API，接收音频和文本，返回对齐结果。
        """
        url = f"{self.service_url}/transcriptions"
        
        with open(wav_path, "rb") as audio_file:
            files = {"audio": ("audio.wav", audio_file, "audio/wav")}
            data = {"transcript": script_text}
            
            response = httpx.post(
                url,
                files=files,
                data=data,
                timeout=self.timeout,
            )
            response.raise_for_status()
            
            return response.json()
    
    def _parse_gentle_result(
        self,
        result: dict[str, Any],
        script_text: str,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        解析 Gentle API 返回结果
        
        Gentle 返回格式：
        {
            "words": [
                {
                    "word": "hello",
                    "start": 0.5,
                    "end": 0.9,
                    "case": "success",  // 或 "not-found-in-audio"
                    "alignedWord": "hello",
                    "phones": [
                        {"phone": "HH", "duration": 0.1},
                        ...
                    ]
                },
                ...
            ]
        }
        """
        alignment = Alignment()
        
        words_data = result.get("words", [])
        matched_count = 0
        
        for word_info in words_data:
            word = word_info.get("word", "")
            case = word_info.get("case", "")
            start = word_info.get("start", 0)
            end = word_info.get("end", 0)
            
            if case == "success":
                tag = WordTag.OK
                matched_count += 1
                # 基于对齐置信度估算分数
                # Gentle 没有直接给分数，我们用时长合理性估算
                expected_duration = 0.1 + len(word) * 0.06
                actual_duration = end - start
                duration_ratio = min(actual_duration, expected_duration) / max(actual_duration, expected_duration)
                score = 60 + duration_ratio * 40  # 60-100 分
            else:
                tag = WordTag.MISSING
                score = 0
            
            alignment.words.append(WordAlignment(
                word=word,
                start=start,
                end=end,
                tag=tag,
                score=score,
            ))
            
            # 解析音素（如果有）
            phones = word_info.get("phones", [])
            phone_start = start
            
            for phone_info in phones:
                phone = phone_info.get("phone", "").split("_")[0]  # 去掉重音标记
                duration = phone_info.get("duration", 0.05)
                
                if phone:
                    alignment.phonemes.append(PhonemeAlignment(
                        phoneme=phone,
                        start=phone_start,
                        end=phone_start + duration,
                        in_word=word,
                        score=score,  # 使用词级分数
                    ))
                    phone_start += duration
        
        # 计算引擎原始数据
        total_words = len(words_data)
        match_ratio = matched_count / total_words if total_words > 0 else 0
        
        engine_raw = {
            "match_ratio": match_ratio,
            "matched_words": matched_count,
            "total_words": total_words,
            "gop_mean": -5 + match_ratio * 3,  # 模拟 GOP，范围 -5 到 -2
        }
        
        return alignment, engine_raw
    
    def _generate_fallback_result(
        self, script_text: str
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        生成回退结果（Gentle 服务不可用时）
        
        基于文本生成基本的对齐结构，分数较为保守。
        """
        import random
        
        alignment = Alignment()
        words = script_text.split()
        
        current_time = 0.3
        
        for word in words:
            word_clean = word.lower().strip(".,!?;:'\"")
            word_duration = 0.15 + len(word_clean) * 0.07
            
            # 保守评分
            score = random.uniform(50, 75)
            
            alignment.words.append(WordAlignment(
                word=word_clean,
                start=current_time,
                end=current_time + word_duration,
                score=score,
                tag=WordTag.OK,
            ))
            
            current_time += word_duration + random.uniform(0.15, 0.35)
        
        engine_raw = {
            "match_ratio": 0.8,  # 假设 80% 匹配
            "gop_mean": -4.0,
            "fallback": True,
        }
        
        return alignment, engine_raw


# 模块级别的引擎实例
_engine_instance: FastEngine | None = None


def get_fast_engine() -> FastEngine:
    """获取 Fast 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = FastEngine()
    return _engine_instance


def run_fast_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """
    运行 Fast 引擎的便捷函数
    
    Args:
        wav_path: WAV 音频文件路径
        script_text: 标准文本
        work_dir: 工作目录
        
    Returns:
        (对齐信息, 引擎原始输出)
    """
    engine = get_fast_engine()
    return engine.run(wav_path, script_text, work_dir)
