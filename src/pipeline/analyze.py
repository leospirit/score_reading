"""
口语评分 CLI 框架 - 分析模块

负责提取 weak_words、weak_phonemes、confusions 等分析结果。
"""
import logging
import math
from collections import Counter
from typing import Any

from src.config import config
from src.pipeline.normalize import normalize_scores
from src.models import (
    Alignment,
    Analysis,
    CompletenessStats,
    Confusion,
    HesitationStats,
    PacePoint,
    PauseInfo,
    PhonemeTag,
    WordTag,
)

logger = logging.getLogger(__name__)


def analyze_results(
    alignment: Alignment,
    script_text: str,
    engine_raw: dict[str, Any],
) -> Analysis:
    """
    分析评分结果，提取关键信息
    
    Args:
        alignment: 对齐信息
        script_text: 标准文本
        engine_raw: 引擎原始输出
        
    Returns:
        分析结果
    """
    logger.info("开始分析评分结果")
    
    analysis = Analysis()
    
    # 0. 预处理：停顿检测（这就地修改 alignment）
    detect_pauses(alignment, script_text)
    
    # 1. 提取 weak words
    analysis.weak_words = extract_weak_words(alignment)
    
    # 2. 提取 weak phonemes
    analysis.weak_phonemes = extract_weak_phonemes(alignment)
    
    # 3. 提取 missing words
    analysis.missing_words = extract_missing_words(alignment, script_text)
    
    # 4. 提取 confusions（如果引擎提供）
    analysis.confusions = extract_confusions(engine_raw)
    
    # 5. 语速趋势分析
    analysis.pace_chart_data = calculate_pace_trend(alignment)
    
    # 6. 完整度高级分析
    analysis.completeness = analyze_completeness(alignment, script_text, analysis.missing_words)
    
    # 7. 迟疑分析 (Basic Text Matching)
    analysis.hesitations = analyze_hesitations(alignment)
    
    logger.info(
        f"分析完成: weak_words={len(analysis.weak_words)}, "
        f"weak_phonemes={len(analysis.weak_phonemes)}, "
        f"missing={len(analysis.missing_words)}, "
        f"confusions={len(analysis.confusions)}"
    )
    
    return analysis


def detect_pauses(alignment: Alignment, script_text: str) -> None:
    """
    检测停顿并更新 Alignment
    
    规则：
    1. Gap >= 0.2s -> Pause
    2. 有标点 (,.!?;) -> Good Pause
    3. 无标点 -> Bad Pause (Hesitation / Broken flow)
    4. 有标点但 Gap 很小 -> Missed Pause (Rushed)
    """
    words = alignment.words
    if not words:
        return

    # 简单对齐：将原始文本分词，尝试与 alignment words 对应以获取标点信息
    # 注意：engine 输出的 word 可能没有标点，而 script_text 有。
    script_tokens = script_text.split()
    token_idx = 0
    
    for i in range(len(words)):
        curr_word = words[i]
        
        # 寻找对应的 script token (含有标点)
        has_punctuation = False
        
        # 简单的向前搜索匹配
        start_idx = token_idx
        while token_idx < len(script_tokens) and token_idx < start_idx + 5: # 限制搜索范围防跑偏
            token = script_tokens[token_idx]
            # 简单模糊匹配（忽略大小写和标点）
            clean_token = token.lower().strip(".,!?;:\"")
            clean_word = curr_word.word.lower().strip(".,!?;:\"")
            
            if clean_token == clean_word or clean_word in clean_token:
                if any(p in token for p in [",", ".", "!", "?", ";"]):
                    has_punctuation = True
                token_idx += 1
                break
            token_idx += 1
            
        # 计算与下一个词的 gap
        if i < len(words) - 1:
            next_word = words[i+1]
            gap = next_word.start - curr_word.end
        else:
            gap = 0.0 # 最后一个词，忽略
            
        # 判定逻辑
        pause_type = None
        duration = round(gap, 2)
        
        if has_punctuation:
            if gap >= 0.2:
                pause_type = "good" # 有标点，有停顿 -> Good
            else:
                pause_type = "missed" # 有标点，无停顿 -> Missed (吞音/急促)
        else:
            if gap >= 0.5: # 无标点，长停顿 -> Bad (Hesitation)
                pause_type = "bad"
            elif gap >= 0.2:
                pause_type = "optional" # 无标点，短停顿 -> Optional (呼吸/断句)
        
        # 记录 Pause
        if pause_type:
             curr_word.pause = PauseInfo(type=pause_type, duration=duration)


def calculate_pace_trend(alignment: Alignment, window_size: float = 2.0) -> list[PacePoint]:
    """
    计算语速趋势 (WPM)
    
    使用滑动窗口。
    """
    if not alignment.words:
        return []
    
    end_time = alignment.words[-1].end
    duration = max(end_time, 1.0)
    
    points = []
    
    # 每 0.5s 采样一次
    step = 0.5
    current_t = 0.0
    
    while current_t <= duration:
        t_start = current_t - window_size / 2
        t_end = current_t + window_size / 2
        
        # 统计窗口内的单词数
        count = 0
        for w in alignment.words:
            # 简单的中心点判定
            w_center = (w.start + w.end) / 2
            if t_start <= w_center < t_end:
                count += 1
        
        # 计算 WPM: (count / window_size_sec) * 60
        # 如果窗口在边缘，可以归一化，但简单起见直接除以 window_size
        wpm = int((count / window_size) * 60)
        points.append(PacePoint(x=round(current_t, 1), y=wpm))
        
        current_t += step
        
    return points


def analyze_completeness(
    alignment: Alignment, 
    script_text: str, 
    missing_words: list[str]
) -> CompletenessStats:
    """
    完整度分析
    """
    FUNCTION_WORDS = {
        "a", "an", "the", "of", "in", "on", "at", "to", "for", "with", "by", 
        "is", "are", "was", "were", "be", "been", "has", "have", "had", 
        "and", "or", "but", "so", "as", "if", "that", "it", "this", "that"
    }
    
    total_words = len(script_text.split())
    if total_words == 0:
        total_words = 1
        
    missing_count = len(missing_words)
    coverage = max(0, min(100, int((1 - missing_count / total_words) * 100)))
    
    func_missed = 0
    key_missed = 0
    
    for w in missing_words:
        if w.lower() in FUNCTION_WORDS:
            func_missed += 1
        else:
            key_missed += 1
            
    # 生成 Tips
    tips = []
    if key_missed > 0:
        tips.append("尝试更仔细地阅读实词（名词、动词），它们承载了句子的核心含义。")
    if func_missed > 2:
        tips.append("注意不要吞掉像 'a', 'the' 这样的小词，虽然它们不重读，但也是句子的一部分。")
    if coverage == 100:
        tips.append("完美！你没有漏掉任何单词。")
    elif coverage > 90 and key_missed == 0:
        tips.append("整体完整度很高，只漏读了一些功能词，继续保持！")
        
    return CompletenessStats(
        title="Completeness",
        score_label="High" if coverage > 90 else ("Medium" if coverage > 70 else "Low"),
        coverage=coverage,
        missing_stats={
            "total": missing_count,
            "keywords": key_missed,
            "function_words": func_missed
        },
        insight=f"Content Coverage: {coverage}%. ({key_missed} keywords missed)",
        tips=tips
    )


def analyze_hesitations(alignment: Alignment) -> HesitationStats | None:
    """
    迟疑/填充词分析
    
    目前仅做简单的文本匹配演示，因为 standard/fast 引擎可能不输出 filler words。
    但在真实 ASR 中，例如 Whisper，可能会输出 "umm", "uh".
    """
    # 检查识别出的单词中是否包含常见 filler
    FILLERS = {"uh", "um", "mm", "er", "ah", "like", "you know", "hmm"}
    
    counts = Counter()
    
    for w in alignment.words:
        clean_w = w.word.lower().strip(".,?!")
        if clean_w in FILLERS:
            counts[clean_w] += 1
            
    if not counts:
        return None # No hesitations found
        
    fillers_list = [{"word": k, "count": v} for k, v in counts.items()]
    
    return HesitationStats(
        score_label="Detected",
        desc="检测到了一些填充词。尝试用停顿代替它们。",
        fillers=fillers_list,
        examples=[], # 暂无上下文例句生成
        tips=["在想说什么的时候，试着深呼吸而不是发出'嗯'的声音。", "尝试放慢语速，给自己更多思考时间。"]
    )


def extract_weak_words(alignment: Alignment) -> list[str]:
    """
    提取分数最低的词
    
    Args:
        alignment: 对齐信息
        
    Returns:
        弱词列表（按分数升序）
    """
    top_n = config.get("analysis.weak_words_top_n", 3)
    ok_threshold = config.get("analysis.word_thresholds.ok", 70)
    
    # 筛选非 missing 的低分词
    weak_candidates = [
        (w.word, w.score)
        for w in alignment.words
        if w.tag != WordTag.MISSING and w.score < ok_threshold
    ]
    
    # 按分数升序排序，取 top N
    weak_candidates.sort(key=lambda x: x[1])
    
    return [word for word, score in weak_candidates[:top_n]]


def extract_weak_phonemes(alignment: Alignment) -> list[str]:
    """
    提取分数最低的音素
    
    Args:
        alignment: 对齐信息
        
    Returns:
        弱音素列表（去重，按出现频率排序）
    """
    top_n = config.get("analysis.weak_phonemes_top_n", 2)
    ok_threshold = config.get("analysis.phoneme_thresholds.ok", 70)
    
    # 统计低分音素出现次数
    weak_phoneme_counts: Counter[str] = Counter()
    
    for phoneme in alignment.phonemes:
        if phoneme.score < ok_threshold:
            # 标准化音素名称（去掉数字后缀等）
            phoneme_name = phoneme.phoneme.rstrip("012").upper()
            weak_phoneme_counts[phoneme_name] += 1
    
    # 取出现最多的 top N
    most_common = weak_phoneme_counts.most_common(top_n)
    
    return [phoneme for phoneme, count in most_common]


def extract_missing_words(alignment: Alignment, script_text: str) -> list[str]:
    """
    提取缺失的词
    
    Args:
        alignment: 对齐信息
        script_text: 标准文本
        
    Returns:
        缺失词列表
    """
    # 从对齐结果中获取 missing 标签的词
    missing_from_alignment = [
        w.word for w in alignment.words if w.tag == WordTag.MISSING
    ]
    
    # 也可以通过对比标准文本和识别结果来补充
    script_words = set(
        word.lower().strip(".,!?;:'\"")
        for word in script_text.split()
        if word.strip()
    )
    
    recognized_words = set(
        w.word.lower() for w in alignment.words if w.tag != WordTag.MISSING
    )
    
    missing_from_comparison = list(script_words - recognized_words)
    
    # 合并去重
    all_missing = list(set(missing_from_alignment + missing_from_comparison))
    
    return all_missing


def extract_confusions(engine_raw: dict[str, Any]) -> list[Confusion]:
    """
    提取音素混淆信息
    
    某些引擎会输出混淆矩阵，标识学生把哪个音素发成了哪个。
    
    Args:
        engine_raw: 引擎原始输出
        
    Returns:
        混淆列表
    """
    top_n = config.get("analysis.confusions_top_n", 2)
    
    confusions: list[Confusion] = []
    
    # 检查引擎是否提供了混淆信息
    confusion_data = engine_raw.get("confusions", [])
    
    if isinstance(confusion_data, list):
        for item in confusion_data:
            if isinstance(item, dict):
                expected = item.get("expected", "")
                got = item.get("got", "")
                count = item.get("count", 1)
                
                if expected and got:
                    confusions.append(Confusion(
                        expected=expected,
                        got=got,
                        count=count,
                    ))
    
    # 按 count 降序排序，取 top N
    confusions.sort(key=lambda x: x.count, reverse=True)
    
    return confusions[:top_n]


def assign_tags(alignment: Alignment) -> None:
    """
    为对齐结果分配标签
    
    根据分数阈值为 words 和 phonemes 分配 ok/weak/poor 标签。
    
    Args:
        alignment: 对齐信息（会被原地修改）
    """
    word_ok = config.get("analysis.word_thresholds.ok", 70)
    word_weak = config.get("analysis.word_thresholds.weak", 40)
    phoneme_ok = config.get("analysis.phoneme_thresholds.ok", 70)
    
    # 分配词标签
    for word in alignment.words:
        if word.tag == WordTag.MISSING:
            continue
        elif word.score >= word_ok:
            word.tag = WordTag.OK
        elif word.score >= word_weak:
            word.tag = WordTag.WEAK
        else:
            word.tag = WordTag.POOR
    
    # 分配音素标签
    for phoneme in alignment.phonemes:
        if phoneme.score >= phoneme_ok:
            phoneme.tag = PhonemeTag.OK
        else:
            phoneme.tag = PhonemeTag.WEAK
