"""
口语评分 CLI 框架 - 路由模块

负责引擎选择和失败回退策略。
"""
import logging
from pathlib import Path
from typing import Any

from src.config import config
from src.models import (
    Alignment,
    AudioMetrics,
    EngineMode,
    WordTag,
)
from src.pipeline.engines.fast import run_fast_engine
from src.pipeline.engines.pro import run_pro_engine
from src.pipeline.engines.standard import run_standard_engine

logger = logging.getLogger(__name__)


def select_engine(
    requested_mode: EngineMode,
    audio_metrics: AudioMetrics,
) -> EngineMode:
    """
    根据请求模式和音频质量选择实际使用的引擎
    
    Args:
        requested_mode: 请求的引擎模式
        audio_metrics: 音频质量指标
        
    Returns:
        实际应使用的引擎模式
    """
    if requested_mode != EngineMode.AUTO:
        logger.info(f"使用指定引擎: {requested_mode.value}")
        return requested_mode
    
    # Auto 模式：根据音频质量选择
    min_duration = config.get("quality_thresholds.min_duration_sec", 2.5)
    max_silence = config.get("quality_thresholds.max_silence_ratio", 0.35)
    min_rms = config.get("quality_thresholds.min_rms_db", -28)
    
    # 检查是否应该使用 fast 引擎
    if audio_metrics.duration_sec < min_duration:
        logger.info(f"音频时长 {audio_metrics.duration_sec:.2f}s < {min_duration}s，选择 fast 引擎")
        return EngineMode.FAST
    
    if audio_metrics.silence_ratio > max_silence:
        logger.info(f"静音占比 {audio_metrics.silence_ratio:.2%} > {max_silence:.0%}，选择 fast 引擎")
        return EngineMode.FAST
    
    if audio_metrics.rms_db < min_rms:
        logger.info(f"RMS {audio_metrics.rms_db:.1f}dB < {min_rms}dB，选择 fast 引擎")
        return EngineMode.FAST
    
    # 默认使用 standard 引擎
    logger.info("音频质量良好，选择 standard 引擎")
    return EngineMode.STANDARD


def calculate_missing_words_ratio(
    script_text: str,
    alignment: Alignment,
) -> float:
    """
    计算缺失词比例
    
    Args:
        script_text: 标准文本
        alignment: 对齐结果
        
    Returns:
        缺失词比例（0-1）
    """
    script_words = set(
        word.lower().strip(".,!?;:'\"")
        for word in script_text.split()
        if word.strip()
    )
    
    missing_words = [w for w in alignment.words if w.tag == WordTag.MISSING]
    
    if not script_words:
        return 0.0
    
    return len(missing_words) / len(script_words)


def run_with_fallback(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
    engine_mode: EngineMode,
    audio_metrics: AudioMetrics,
) -> tuple[Alignment, dict[str, Any], str, list[str]]:
    """
    运行引擎并处理失败回退
    
    Args:
        wav_path: WAV 文件路径
        script_text: 标准文本
        work_dir: 工作目录
        engine_mode: 引擎模式
        audio_metrics: 音频质量指标
        
    Returns:
        (对齐信息, 引擎原始输出, 实际使用的引擎, 回退链路)
    """
    # 选择初始引擎
    selected_engine = select_engine(engine_mode, audio_metrics)
    
    fallback_chain: list[str] = []
    max_missing_ratio = config.get("fallback.max_missing_words_ratio", 0.25)
    
    def try_engine(mode: EngineMode) -> tuple[Alignment, dict[str, Any]] | None:
        """尝试运行指定引擎"""
        try:
            if mode == EngineMode.STANDARD:
                return run_standard_engine(wav_path, script_text, work_dir)
            elif mode == EngineMode.FAST:
                return run_fast_engine(wav_path, script_text, work_dir)
            elif mode == EngineMode.PRO:
                return run_pro_engine(wav_path, script_text, work_dir)
            else:
                return None
        except Exception as e:
            logger.warning(f"{mode.value} 引擎失败: {e}")
            return None
    
    # 尝试运行选定的引擎
    current_engine = selected_engine
    result = try_engine(current_engine)
    
    if result:
        alignment, engine_raw = result
        
        # 检查是否需要因为 missing words 过多而回退
        missing_ratio = calculate_missing_words_ratio(script_text, alignment)
        
        if missing_ratio > max_missing_ratio and current_engine != EngineMode.FAST:
            logger.warning(
                f"缺失词比例 {missing_ratio:.2%} > {max_missing_ratio:.0%}，触发回退"
            )
            fallback_chain.append(current_engine.value)
            
            # 回退到 fast 引擎
            fallback_result = try_engine(EngineMode.FAST)
            if fallback_result:
                alignment, engine_raw = fallback_result
                current_engine = EngineMode.FAST
        
        return alignment, engine_raw, current_engine.value, fallback_chain
    
    # 引擎失败，尝试回退
    fallback_chain.append(current_engine.value)
    
    # 定义回退顺序
    fallback_order = {
        EngineMode.PRO: [EngineMode.STANDARD, EngineMode.FAST],
        EngineMode.STANDARD: [EngineMode.FAST],
        EngineMode.FAST: [],
    }
    
    for fallback_engine in fallback_order.get(current_engine, []):
        logger.info(f"尝试回退到 {fallback_engine.value} 引擎")
        result = try_engine(fallback_engine)
        
        if result:
            alignment, engine_raw = result
            return alignment, engine_raw, fallback_engine.value, fallback_chain
        
        fallback_chain.append(fallback_engine.value)
    
    # 所有引擎都失败
    raise RuntimeError(f"所有引擎都失败，回退链路: {' -> '.join(fallback_chain)}")
