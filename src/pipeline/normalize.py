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
    
    采用 Sigmoid (S型曲线) 函数进行非线性归一化，以提高不同水平学生的区分度。
    
    Args:
        raw_score: 原始 GOP 分数（通常为负数）
        
    Returns:
        0-100 分制分数
    """
    mode = config.get("normalization.gop.mode", "linear")
    
    if mode == "sigmoid":
        import math
        # Sigmoid 公式: 100 / (1 + exp(-k * (raw_score - center)))
        k = config.get("normalization.gop.sigmoid.k", 1.5)
        center = config.get("normalization.gop.sigmoid.center", -4.0)
        
        # GOP 越接近 0 越好，所以 raw_score - center 正值代表优秀
        score = 100 / (1 + math.exp(-k * (raw_score - center)))
        return max(0, min(100, score))
    else:
        # 传统线性映射 - 中性平衡
        # 范围扩大到 -10，使极差的分数也不至于掉到 10 分左右
        gop_min = config.get("normalization.gop.min", -10.0)
        gop_max = config.get("normalization.gop.max", -1.0)
        clamped = max(gop_min, min(gop_max, raw_score))
        normalized = (clamped - gop_min) / (gop_max - gop_min) * 100
        return max(0, min(100, normalized))


def calculate_fluency_score(
    audio_metrics: AudioMetrics,
    alignment: Alignment,
) -> float:
    """
    计算流利度分数
    
    基于语速(WPM)和异常停顿计算流利度。
    
    语速评分标准（小学生朗读）：
    - 80-120 WPM: 优秀（90-100分）
    - 60-80 或 120-150 WPM: 良好（70-90分）
    - 40-60 或 150-180 WPM: 一般（50-70分）
    - <40 或 >180 WPM: 较差（<50分）
    
    Args:
        audio_metrics: 音频质量指标
        alignment: 对齐信息
        
    Returns:
        0-100 分制流利度分数
    """
    # 计算实际语速（WPM = Words Per Minute）
    word_count = len([w for w in alignment.words if w.end > 0])  # 只计有时间戳的词
    duration_sec = audio_metrics.duration_sec
    
    if duration_sec <= 0 or word_count == 0:
        logger.warning("无法计算语速：时长或词数为 0")
        return 50.0  # 返回中等分数
    
    wpm = (word_count / duration_sec) * 60
    logger.info(f"语速计算: {word_count} 词 / {duration_sec:.1f}s = {wpm:.1f} WPM")
    
    # 语速评分（核心指标）
    # NOTE: 小学生朗读最佳语速约 80-120 WPM
    if 80 <= wpm <= 120:
        wpm_score = 98  # 最佳区间，给予高分
    elif 60 <= wpm <= 150:
        # 增加衰减斜率，让低于 80 WPM 的分数下降更快
        if wpm < 80:
            # 60 WPM 从原来的 70 调低到 60
            wpm_score = 60 + (wpm - 60) / 20 * 30
        else:
            wpm_score = 98 - (wpm - 120) / 30 * 28
    elif 40 <= wpm <= 180:
        if wpm < 60:
            # 40 WPM 降到 30
            wpm_score = 30 + (wpm - 40) / 20 * 30
        else:
            wpm_score = 60 - (wpm - 150) / 30 * 20
    else:
        wpm_score = 25  # 极端语速，大幅降分
    
    # 停顿分析（辅助指标）
    # 从配置读取惩罚权重
    pause_weight = config.get("normalization.fluency.pause_penalty_weight", 20)
    pause_penalty = 0
    if alignment.words and len(alignment.words) > 1:
        # 降低长停顿阈值（从 2.0 降到 1.2）
        long_pause_threshold = 1.2
        very_long_pause_threshold = 3.0
        
        for i in range(1, len(alignment.words)):
            prev_word = alignment.words[i - 1]
            curr_word = alignment.words[i]
            
            if prev_word.end > 0 and curr_word.start > 0:
                gap = curr_word.start - prev_word.end
                
                if gap > very_long_pause_threshold:
                    pause_penalty += 8  # 增加惩罚力度
                elif gap > long_pause_threshold:
                    pause_penalty += 3
        
        pause_penalty = min(30, pause_penalty) # 上限 30 分
    
    # 综合分数
    score = wpm_score - pause_penalty
    
    logger.info(f"流利度计算: WPM分={wpm_score:.1f}, 停顿惩罚={pause_penalty}, 最终={score:.1f}")
    
    return max(0, min(100, score))


def calculate_intonation_score(audio_metrics: AudioMetrics, pitch_contour: list = None) -> float:
    """
    计算语调分数（优化方案）
    """
    import random
    import numpy as np
    
    base_score = 88.0
    
    # 1. 维度：音高起伏度 (Pitch Variation)
    if pitch_contour and len(pitch_contour) > 10:
        # 获取 F0 数组
        # 注意：engine_raw 中 pitch_contour 里的 key 是 'f' (Standard) 或 'f' (Whisper)
        f_list = [p.get("f", p.get("f0", 0)) for p in pitch_contour]
        pitches = [f for f in f_list if f > 50]
        
        if len(pitches) > 10:
            # 计算变异系数 (CV)
            cv = (np.std(pitches) / np.mean(pitches)) * 100
            if cv < 12: # 太单调
                base_score -= 15
            elif 18 <= cv <= 35: # 很丰富
                base_score += 5
    
    # 2. 维度：能量质量 (RMS)
    if audio_metrics.rms_db < -25:
        base_score -= random.uniform(15, 25)
    elif audio_metrics.rms_db < -18:
        base_score -= random.uniform(5, 10)
    
    # 3. 维度：静音率惩罚
    if audio_metrics.silence_ratio > 0.5:
        base_score -= random.uniform(20, 30)
    elif audio_metrics.silence_ratio > 0.3:
        base_score -= random.uniform(8, 15)
        
    # 增加细微抖动，避免出现死板的固定分
    base_score += random.uniform(-1.5, 1.5)
    
    return max(0, min(100, base_score))


def calculate_completeness_score(
    script_text: str,
    alignment: Alignment,
) -> float:
    """
    计算完整度分数
    """
    # 使用正则解析标准文本中的词，确保与识别引擎分词逻辑一致
    import re
    script_words = [
        word.lower()
        for word in re.findall(r"[a-zA-Z']+", script_text)
    ]
    
    # 获取识别到的词（同样使用正则清理，以防万一）
    recognized_words = [
        w.word.lower() for w in alignment.words if w.tag != WordTag.MISSING
    ]
    
    if not script_words:
        return 100.0
    
    # 使用简单匹配计数，允许重复词
    from collections import Counter
    s_counter = Counter(script_words)
    r_counter = Counter(recognized_words)
    
    matches = 0
    for w, count in s_counter.items():
        matches += min(count, r_counter.get(w, 0))
    
    score = (matches / len(script_words)) * 100
    
    return max(0, min(100, score))


def calculate_overall_score(scores: Scores) -> float:
    """
    计算综合分数 - 提高区分度
    """
    # 权重配置 (调整：提高发音权重，降低完整度偏移)
    weights = {
        "pronunciation": 0.55,   # 0.4 -> 0.55
        "fluency": 0.25,        # 保持
        "intonation": 0.15,      # 保持
        "completeness": 0.05,    # 0.2 -> 0.05 (降低完整度带来的底分效应)
    }
    
    raw_overall = (
        scores.pronunciation_100 * weights["pronunciation"]
        + scores.fluency_100 * weights["fluency"]
        + scores.intonation_100 * weights["intonation"]
        + scores.completeness_100 * weights["completeness"]
    )
    
    # 移除过度严苛的非线性惩罚 (Remove math.pow 1.25)
    # 使 80 分就是真实的 80 分，不再被强行降至 70+
    return round(raw_overall, 1)


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
    
    # 发音分数
    if "pronunciation_score" in engine_raw:
        pronunciation = engine_raw["pronunciation_score"]
        logger.info(f"使用引擎直接提供的发音分: {pronunciation}")
    else:
        gop_mean = engine_raw.get("gop_mean", -5.0)
        pronunciation = normalize_gop_score(gop_mean)
    
    # 流利度分数
    if "fluency_score" in engine_raw:
        fluency = engine_raw["fluency_score"]
        logger.info(f"使用引擎直接提供的流利分: {fluency}")
    else:
        fluency = calculate_fluency_score(audio_metrics, alignment)
    
    # 语调分数
    if "intonation_score" in engine_raw:
        intonation = engine_raw["intonation_score"]
        logger.info(f"使用引擎直接提供的语调分: {intonation}")
    else:
        pitch_contour = engine_raw.get("pitch_contour", [])
        intonation = calculate_intonation_score(audio_metrics, pitch_contour)
    
    # 完整度分数
    if "completeness_score" in engine_raw:
        completeness = engine_raw["completeness_score"]
        logger.info(f"使用引擎直接提供的完整分: {completeness}")
    else:
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
    # 全面放宽：OK 阈值由 75 降至 60，WEAK 阈值由 45 降至 35
    ok_threshold = config.get("analysis.word_thresholds.ok", 60)
    weak_threshold = config.get("analysis.word_thresholds.weak", 35)
    
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
