"""
口语评分 CLI 框架 - Pro 引擎（Stub）

预留的高级引擎接口，后续可接入 GOPT 等更高级的模型。
"""
import logging
from pathlib import Path
from typing import Any

from src.models import Alignment, WordTag
from src.pipeline.engines.wav2vec2 import Wav2Vec2Engine
from src.pipeline.engines.whisper_engine import WhisperEngine
from src.config import config

logger = logging.getLogger(__name__)


class ProEngine:
    """
    Pro 引擎 (AI 增强型)
    
    使用双引擎协同模式：
    1. Wav2Vec2 Engine: 负责精密的时间对齐和声学评估。
    2. Whisper Engine (AI ASR): 负责语义转录核对。
    
    如果声学引擎认为 OK，但 AI 转录出的单词与脚本不符（语义偏离），则判定为错误。
    """
    
    def __init__(self) -> None:
        self.whisper = WhisperEngine()
    
    def run(
        self,
        wav_path: Path,
        script_text: str,
        word_dir: Path,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Pro 引擎
        """
        logger.info("Pro 引擎：启动高精度模式")
        
        # 1. 优先尝试 Gemini 多模态专家引擎
        gemini_key = config.get("engines.gemini.api_key")
        if gemini_key:
            try:
                from src.pipeline.engines.gemini import run_gemini_engine
                logger.info("Pro 引擎：检测到 Gemini 配置，优先使用多模态专家评测")
                return run_gemini_engine(wav_path, script_text, word_dir)
            except Exception as e:
                logger.warning(f"Gemini 引擎运行失败，将尝试其他 Pro 选项: {e}")

        # 2. 尝试 Azure 云端专家引擎
        azure_key = config.get("engines.azure.api_key")
        if azure_key:
            try:
                from src.pipeline.engines.azure import run_azure_engine
                logger.info("Pro 引擎：检测到 Azure 配置，尝试使用云端专家评测")
                return run_azure_engine(wav_path, script_text, word_dir)
            except Exception as e:
                logger.warning(f"Azure 引擎运行失败，将降级到本地 Pro 模式: {e}")

        # 3. 回退到本地增强对齐模式 (Standard + Whisper)
        wav2vec2 = Wav2Vec2Engine()
        alignment, engine_raw = wav2vec2.run(wav_path, script_text, work_dir)
        
        # 2. 获取 AI 语义转录
        try:
            whisper_alignment, whisper_raw = self.whisper.run(wav_path, script_text, work_dir)
            transcript_words = [w.word.lower().strip(".,!?;:'\"") for w in whisper_alignment.words if w.tag != WordTag.MISSING]
            
            # 3. 语义交叉校验 (Semantic Referee)
            # 我们核对脚本中的每个词，看看 AI 实际听到的是什么
            script_tokens = [w.word.lower().strip(".,!?;:'\"") for w in alignment.words]
            
            semantic_conflicts = 0
            conflict_details = []
            
            for i, word_align in enumerate(alignment.words):
                if word_align.tag == WordTag.MISSING:
                    continue
                
                target = word_align.word.lower().strip(".,!?;:'\"")
                
                # 寻找匹配
                found_word = None
                search_window = transcript_words[max(0, i-2) : min(len(transcript_words), i+3)]
                
                if target in search_window:
                    found_word = target
                else:
                    # 尝试寻找最相似的备选词（捕获单复数错误等）
                    for sw in search_window:
                        if sw.startswith(target[:3]) or target.startswith(sw[:3]):
                            found_word = sw
                            break
                
                if found_word == target:
                    pass # 匹配成功
                else:
                    # 关键逻辑：如果 AI 听错了，或者发现显著差异（如单复数）
                    if word_align.tag == WordTag.OK or word_align.score > 70:
                        logger.warning(f"AI 语义冲突: 脚本词 '{target}'，AI 听到的是 '{found_word or 'Nothing'}'")
                        word_align.tag = WordTag.WEAK
                        word_align.score = min(word_align.score, 68.5)
                        semantic_conflicts += 1
                        conflict_details.append({
                            "word": word_align.word,
                            "expected": target,
                            "got": found_word or "???",
                        })
            
            engine_raw["ai_referee"] = {
                "conflicts": semantic_conflicts,
                "conflict_details": conflict_details,
                "whisper_transcript": transcript_words,
                "status": "completed"
            }
            logger.info(f"Pro 引擎：语义校验完成，发现 {semantic_conflicts} 处冲突")
            
        except Exception as e:
            logger.error(f"Pro 引擎 AI 校验失败: {e}")
            engine_raw["ai_referee"] = {"status": "failed", "error": str(e)}

        engine_raw["engine_type"] = "pro_v1"
        return alignment, engine_raw


# 模块级别的引擎实例
_engine_instance: ProEngine | None = None


def get_pro_engine() -> ProEngine:
    """获取 Pro 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ProEngine()
    return _engine_instance


def run_pro_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """
    运行 Pro 引擎的便捷函数
    
    Args:
        wav_path: WAV 音频文件路径
        script_text: 标准文本
        work_dir: 工作目录
        
    Returns:
        (对齐信息, 引擎原始输出)
    """
    engine = get_pro_engine()
    return engine.run(wav_path, script_text, work_dir)
