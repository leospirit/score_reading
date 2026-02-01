"""
口语评分 CLI 框架 - 分数归一化模块

负责将各引擎的原始分数映射到统一的 0-100 分制。
"""
import logging
from typing import Any

from src.config import config
from src.models import (
    Alignment,
    AudioMetrics,
    PhonemeTag,
    Scores,
    WordTag,
)

logger = logging.getLogger(__name__)


def normalize_gop_score(raw_score: float) -> float:
    """
    归一化 GOP 分数
    
    GOP（Goodness of Pronunciation）分数通常为负数，越接近 0 越好。
    将其映射到 0-100 分制。
    
    Args:
        raw_score: 原始 GOP 分数（通常为负数）
        
    Returns:
        0-100 分制分数
    """
    gop_min = config.get("normalization.gop.min", -10.0)
    gop_max = config.get("normalization.gop.max", 0.0)
    
    # 限制在有效范围内
    clamped = max(gop_min, min(gop_max, raw_score))
    
    # 线性映射到 0-100
    normalized = (clamped - gop_min) / (gop_max - gop_min) * 100
    
    return max(0, min(100, normalized))


def calculate_fluency_score(
    audio_metrics: AudioMetrics,
    alignment: Alignment,
) -> float:
    """
    计算流利度分数
    
    基于静音占比和异常停顿计算流利度。
    
    Args:
        audio_metrics: 音频质量指标
        alignment: 对齐信息
        
    Returns:
        0-100 分制流利度分数
    """
    silence_weight = config.get("normalization.fluency.silence_penalty_weight", 50)
    pause_weight = config.get("normalization.fluency.pause_penalty_weight", 20)
    
    # 基础分 100 分
    score = 100.0
    
    # 静音惩罚：silence_ratio 每增加 0.1 扣 silence_weight * 0.1 分
    silence_penalty = audio_metrics.silence_ratio * silence_weight
    score -= silence_penalty
    
    # 异常停顿惩罚：检测词间过长停顿
    # NOTE: 超过 0.8s 的停顿视为异常
    if alignment.words:
        pause_threshold = 0.8
        pause_count = 0
        
        for i in range(1, len(alignment.words)):
            gap = alignment.words[i].start - alignment.words[i - 1].end
            if gap > pause_threshold:
                pause_count += 1
        
        pause_penalty = pause_count * pause_weight
        score -= pause_penalty
    
    return max(0, min(100, score))


def calculate_intonation_score(audio_metrics: AudioMetrics) -> float:
    """
    计算语调分数（简化方案）
    
    基于能量变化模式估算语调自然度。
    完整方案应使用 F0（基频）轮廓分析。
    
    Args:
        audio_metrics: 音频质量指标
        
    Returns:
        0-100 分制语调分数
    """
    # NOTE: 简化方案，使用 RMS 和静音比估算
    # 正常朗读的 RMS 应在 -25dB 到 -10dB 之间
    # 静音比过高说明语调可能不流畅
    
    base_score = 80.0  # 基础分
    
    # RMS 过低惩罚
    if audio_metrics.rms_db < -25:
        base_score -= 10
    elif audio_metrics.rms_db < -20:
        base_score -= 5
    
    # RMS 过高可能是过度强调
    if audio_metrics.rms_db > -8:
        base_score -= 5
    
    # 静音比影响
    if audio_metrics.silence_ratio > 0.3:
        base_score -= 10
    elif audio_metrics.silence_ratio > 0.2:
        base_score -= 5
    
    return max(0, min(100, base_score))


def calculate_completeness_score(
    script_text: str,
    alignment: Alignment,
) -> float:
    """
    计算完整度分数
    
    基于缺失词比例计算。
    
    Args:
        script_text: 标准文本
        alignment: 对齐信息
        
    Returns:
        0-100 分制完整度分数
    """
    # 解析标准文本中的词
    script_words = set(
        word.lower().strip(".,!?;:'\"")
        for word in script_text.split()
        if word.strip()
    )
    
    # 获取识别到的词
    recognized_words = set(
        w.word.lower() for w in alignment.words if w.tag != WordTag.MISSING
    )
    
    if not script_words:
        return 100.0
    
    # 计算缺失比例
    missing_count = len(script_words - recognized_words)
    missing_ratio = missing_count / len(script_words)
    
    # 转换为分数
    score = 100 * (1 - missing_ratio)
    
    return max(0, min(100, score))


def calculate_overall_score(scores: Scores) -> float:
    """
    计算综合分数
    
    加权平均各维度分数。
    
    Args:
        scores: 各维度分数
        
    Returns:
        0-100 分制综合分数
    """
    # 权重配置
    weights = {
        "pronunciation": 0.4,
        "fluency": 0.25,
        "intonation": 0.15,
        "completeness": 0.2,
    }
    
    overall = (
        scores.pronunciation_100 * weights["pronunciation"]
        + scores.fluency_100 * weights["fluency"]
        + scores.intonation_100 * weights["intonation"]
        + scores.completeness_100 * weights["completeness"]
    )
    
    return round(overall, 1)


def normalize_scores(
    engine_raw: dict[str, Any],
    audio_metrics: AudioMetrics,
    alignment: Alignment,
    script_text: str,
) -> Scores:
    """
    归一化所有分数
    
    将引擎原始分数和分析结果转换为统一的 0-100 分制。
    
    Args:
        engine_raw: 引擎原始输出
        audio_metrics: 音频质量指标
        alignment: 对齐信息
        script_text: 标准文本
        
    Returns:
        归一化后的分数
    """
    logger.info("开始分数归一化")
    
    # 发音分数（基于 GOP）
    gop_mean = engine_raw.get("gop_mean", -5.0)
    pronunciation = normalize_gop_score(gop_mean)
    
    # 流利度分数
    fluency = calculate_fluency_score(audio_metrics, alignment)
    
    # 语调分数
    intonation = calculate_intonation_score(audio_metrics)
    
    # 完整度分数
    completeness = calculate_completeness_score(script_text, alignment)
    
    scores = Scores(
        pronunciation_100=pronunciation,
        fluency_100=fluency,
        intonation_100=intonation,
        completeness_100=completeness,
    )
    
    # 计算综合分
    scores.overall_100 = calculate_overall_score(scores)
    
    logger.info(
        f"分数归一化完成: 综合={scores.overall_100}, "
        f"发音={pronunciation:.1f}, 流利={fluency:.1f}, "
        f"语调={intonation:.1f}, 完整={completeness:.1f}"
    )
    
    return scores


def assign_word_tags(alignment: Alignment) -> None:
    """
    为对齐结果中的词分配标签
    
    根据分数阈值分配 ok/weak/poor 标签。
    
    Args:
        alignment: 对齐信息（会被原地修改）
    """
    ok_threshold = config.get("analysis.word_thresholds.ok", 70)
    weak_threshold = config.get("analysis.word_thresholds.weak", 40)
    
    for word in alignment.words:
        if word.tag == WordTag.MISSING:
            continue
        elif word.score >= ok_threshold:
            word.tag = WordTag.OK
        elif word.score >= weak_threshold:
            word.tag = WordTag.WEAK
        else:
            word.tag = WordTag.POOR


def assign_phoneme_tags(alignment: Alignment) -> None:
    """
    为对齐结果中的音素分配标签
    
    Args:
        alignment: 对齐信息（会被原地修改）
    """
    ok_threshold = config.get("analysis.phoneme_thresholds.ok", 70)
    
    for phoneme in alignment.phonemes:
        if phoneme.score >= ok_threshold:
            phoneme.tag = PhonemeTag.OK
        else:
            phoneme.tag = PhonemeTag.WEAK
