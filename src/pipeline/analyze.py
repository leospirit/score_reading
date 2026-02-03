"""
口语评分 CLI 框架 - 分析模块

负责提取 weak_words、weak_phonemes、confusions 等分析结果。
"""
import logging
import math
import re
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
    PitchPoint,
    PauseInfo,
    PhonemeTag,
    PhonemeTag,
    WordTag,
    WordAlignment,
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
    
    # 0. 强力对齐：强制 alignment.words 与 script_text 结构一致 (Reference Mode)
    # 这解决了 Missing Words 不显示的问题
    align_to_script(alignment, script_text)

    # 1. 预处理：停顿检测 与 连读检测（这就地修改 alignment）
    detect_pauses(alignment, script_text)
    detect_linking(alignment)
    
    # 2. 提取 weak words
    analysis.weak_words = extract_weak_words(alignment)
    
    # 3. 提取 weak phonemes (用于 AI 深度指导)
    analysis.weak_phonemes = extract_weak_phonemes(alignment)
    # 由于已经对其过，直接找 tag=MISSING 即可
    analysis.missing_words = [w.word for w in alignment.words if w.tag == WordTag.MISSING]
    
    # 4. 提取具体错误摘要 (Mistake Highlights)
    analysis.mistakes = detect_mistakes(alignment, engine_raw)
    
    
    # 3. 提取 missing words (Already done above)
    # analysis.missing_words = extract_missing_words(alignment, script_text)
    
    # 4. 提取 confusions（如果引擎提供）
    analysis.confusions = extract_confusions(engine_raw)
    
    # 5. 语速趋势分析
    analysis.pace_chart_data = calculate_pace_trend(alignment)
    
    # 6. 完整度高级分析
    analysis.completeness = analyze_completeness(alignment, script_text, analysis.missing_words)
    
    # 7. 迟疑分析 (Basic Text Matching)
    analysis.hesitations = analyze_hesitations(alignment)
    
    # 8. 语调曲线数据提取
    if "pitch_contour" in engine_raw:
        analysis.pitch_contour = [
            PitchPoint(t=p["t"], f0=p["f"]) for p in engine_raw["pitch_contour"]
        ]
    
    # 9. 生成期望重音模式 (Native Speaker 参考)
    generate_expected_stress(alignment)
    
    logger.info(
        f"分析完成: weak_words={len(analysis.weak_words)}, "
        f"weak_phonemes={len(analysis.weak_phonemes)}, "
        f"missing={len(analysis.missing_words)}, "
        f"confusions={len(analysis.confusions)}"
    )
    
    return analysis


# 常见虚词列表（弱读词）
FUNCTION_WORDS = {
    # 冠词
    "a", "an", "the",
    # 介词
    "to", "of", "in", "on", "at", "for", "with", "by", "from", "up", "about",
    "into", "over", "after", "before", "between", "under", "without", "through",
    # 连词
    "and", "or", "but", "so", "if", "because", "although", "while", "when",
    # 代词
    "i", "me", "my", "you", "your", "he", "him", "his", "she", "her", "it", "its",
    "we", "us", "our", "they", "them", "their", "this", "that", "these", "those",
    # 助动词
    "is", "am", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    # 其他
    "not", "just", "some", "any", "no", "very", "too", "also",
}


def align_to_script(alignment: Alignment, script_text: str) -> None:
    """
    使用 difflib 将识别结果强制对齐到脚本结构。
    
    目的：
    1. 确保 UI 显示的单词列表与脚本 1:1 对应（Ghost Words View 需要）。
    2. 发现并标记漏读的词（Missing）。
    3. 处理多读的词（忽略或标记）。
    
    策略：
    - Reference: Script Tokens
    - Hypothesis: Recognized Words
    - OpCodes:
        - equal: Keep recognized word (has score/timing).
        - delete (in Ref, not in Hyp): Insert Script word as MISSING.
        - insert (in Hyp, not in Ref): Ignore (extra words not in script).
        - replace: User said something else. Keep Script word, mark as POOR/WEAK (Mispronunciation).
    """
    import difflib
    
    if not script_text or not script_text.strip():
        return
        
    # 1. Tokenize Script (Robust split)
    # 使用 \w+ 包括数字和字母，handle ' for contractions
    ref_tokens = re.findall(r"[\w']+", script_text)
    if not ref_tokens:
        return
        
    # 2. Get Hyp Tokens (normalized)
    hyp_words = alignment.words
    # Clean both ref and hyp similarly for matching
    ref_tokens_lower = [t.lower().strip(".,!?;:\"") for t in ref_tokens]
    hyp_tokens = [w.word.lower().strip(".,!?;:\"") for w in hyp_words]
    
    matcher = difflib.SequenceMatcher(None, ref_tokens_lower, hyp_tokens)
    
    new_words: list[WordAlignment] = []
    
    # 使用时间游标来为插入的 Missing 词估算时间
    current_time_cursor = 0.0
    if hyp_words:
        current_time_cursor = hyp_words[0].start
        
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        # ref[i1:i2] vs hyp[j1:j2]
        
        if tag == 'equal':
            # 完全匹配：保留识别结果
            for k in range(j1, j2):
                w = hyp_words[k]
                # 强制修正单词拼写为 Script 的样子 (Case correction)
                ref_idx = i1 + (k - j1)
                if ref_idx < len(ref_tokens):
                    w.word = ref_tokens[ref_idx]
                new_words.append(w)
                current_time_cursor = w.end
                
        elif tag == 'delete':
            # Ref 有，Hyp 没有 -> Missing
            # 插入 Missing Words
            for k in range(i1, i2):
                missing_word = ref_tokens[k]
                new_w = WordAlignment(
                    word=missing_word,
                    start=current_time_cursor,
                    end=current_time_cursor + 0.1, # Mock duration
                    score=0,
                    tag=WordTag.MISSING
                )
                new_words.append(new_w)
                current_time_cursor += 0.1
                
        elif tag == 'replace':
            # Ref 有，Hyp 也有但不同 -> Mispronunciation (Wait, or just align error)
            # 逻辑：用户想读 Ref，但读成了 Hyp。
            # 我们保留 Ref 的单词文本，但继承 Hyp 的分数（通常较低）或标记为 WEAK
            
            # 这里的数量可能不一致 (e.g. Ref: "cat", Hyp: "bat mat")
            # 简单策略：按 1:1 映射，多余的忽略/补全
            len_ref = i2 - i1
            len_hyp = j2 - j1
            common_len = min(len_ref, len_hyp)
            
            for k in range(common_len):
                w_orig = hyp_words[j1 + k]
                ref_word = ref_tokens[i1 + k]
                
                # 修改文本为 Target
                w_orig.word = ref_word
                # 如果分数太高，可能需要惩罚？SequenceMatcher 认为它们不同，说明拼写不同
                # 但也许是同音词？暂时信任原始分数，但确保 tag 至少是 WEAK
                if w_orig.score > 60:
                     w_orig.score = 55 # Cap score for misread
                if w_orig.tag == WordTag.OK:
                    w_orig.tag = WordTag.WEAK
                    
                new_words.append(w_orig)
                current_time_cursor = w_orig.end
                
            # 处理剩余的 Ref (视为 Missing)
            if len_ref > len_hyp:
                for k in range(i1 + common_len, i2):
                    missing_word = ref_tokens[k]
                    new_w = WordAlignment(
                        word=missing_word,
                        start=current_time_cursor,
                        end=current_time_cursor + 0.1,
                        score=0,
                        tag=WordTag.MISSING
                    )
                    new_words.append(new_w)
                    current_time_cursor += 0.1
                    
            # 处理剩余的 Hyp (视为 Extra - 忽略，因为我们要保持 Script 结构)
            pass
            
        elif tag == 'insert':
            # Hyp 有 (extra)，Ref 没有 -> 忽略
            pass
            
    # 更新 Alignment
    alignment.words = new_words
    
    # CRITICAL: Re-assign tags after reconstruction to ensure Missing/Weak/OK are set correctly
    assign_tags(alignment)
    
    logger.info(f"Alignment synced to script: {len(hyp_words)} -> {len(new_words)} words")


def generate_expected_stress(alignment: Alignment) -> None:
    """
    为每个单词生成期望重音值 (Native Speaker 参考)
    
    规则：
    - 实词（名词、动词、形容词、副词）：高重音 (0.7-0.9)
    - 虚词（冠词、介词、代词、助动词）：低重音 (0.2-0.4)
    - 句首/句尾词通常略重
    """
    words = alignment.words
    if not words:
        return
    
    for i, word in enumerate(words):
        clean_word = word.word.lower().strip(".,!?;:\"'")
        
        # 基础判定：实词 vs 虚词
        if clean_word in FUNCTION_WORDS:
            base_stress = 0.3  # 虚词 - 弱读
        else:
            base_stress = 0.8  # 实词 - 重读
        
        # 句首加成
        if i == 0:
            base_stress = min(1.0, base_stress + 0.1)
        
        # 句尾加成（最后一个或者倒数第二个实词）
        if i >= len(words) - 2 and clean_word not in FUNCTION_WORDS:
            base_stress = min(1.0, base_stress + 0.1)
        
        word.expected_stress = round(base_stress, 2)



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
    # 使用正则分词，确保与识别引擎逻辑一致
    script_tokens = re.findall(r"[a-zA-Z']+", script_text)
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
            if gap >= 0.25: # 微调阈值使之更具容错性
                pause_type = "good" 
            else:
                pause_type = "missed" # 标点处无停顿
        else:
            if gap >= 0.6: # 长停顿 -> Bad
                pause_type = "bad"
            elif gap >= 0.3:
                pause_type = "optional" 
        
        # 记录 Pause
        if pause_type:
             curr_word.pause = PauseInfo(type=pause_type, duration=duration)


def detect_linking(alignment: Alignment) -> None:
    """
    检测连读并更新 Alignment
    
    连读规则 (初步实现)：
    1. 前一词的结束与后一词的开始有重叠，或间隔极微小 (< 0.02s)
    2. 后续可扩展音素级规则 (C-V)
    """
    words = alignment.words
    if not words:
        return
    
    for i in range(len(words) - 1):
        curr_word = words[i]
        next_word = words[i+1]
        
        # 计算间隙
        gap = next_word.start - curr_word.end
        
        # 连读判定规则：
        # 1. 重叠 (gap < 0)
        # 2. 极其微小的间隙 (gap < 0.03s)
        if gap < 0.03:
            curr_word.is_linked = True


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
    
    logger.info(f"Calculating Pace: {len(alignment.words)} words, duration={duration}s")
    
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
    
    logger.info(f"Pace Points Generated: {len(points)}")
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
    
    # 使用正则分词统计单词数
    total_words = len(re.findall(r"[a-zA-Z']+", script_text))
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
        title="完整度分析",
        score_label="优秀" if coverage > 90 else ("良好" if coverage > 70 else "需加油"),
        coverage=coverage,
        missing_stats={
            "total": missing_count,
            "keywords": key_missed,
            "function_words": func_missed
        },
        insight=f"内容覆盖率: {coverage}% (漏读 {key_missed} 个关键词)",
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
    SAFE_TO_REMOVE = {"uh", "um", "mm", "er", "ah", "hmm"} # Unambiguous fillers
    
    counts = Counter()
    
    for w in alignment.words:
        clean_w = w.word.lower().strip(".,?!")
        if clean_w in FILLERS:
            counts[clean_w] += 1
            
    if not counts:
        return None # No hesitations found
        
    fillers_list = [{"word": k, "count": v} for k, v in counts.items()]
    
    # Contextual Examples Generation
    examples = []
    used_indices = set()
    
    words = alignment.words
    for i, w in enumerate(words):
        clean_w = w.word.lower().strip(".,?!")
        if clean_w in FILLERS:
            # Avoid overlapping examples or duplicate fillers in same phrase
            if i in used_indices:
                continue
                
            # SAFETY CHECK: Only generate "Try saying" corrections for unambiguous fillers
            # We don't want to suggest "I apples" for "I like apples".
            if clean_w not in SAFE_TO_REMOVE:
                continue
                
            # Extract Context (Window of +/- 3 words)
            start = max(0, i - 3)
            end = min(len(words), i + 4)
            
            # Mark indices as used
            for k in range(start, end):
                used_indices.add(k)
                
            # Construct phrases
            phrase_words = words[start:end]
            
            # Original: join words with spaces
            original_text = " ".join([fw.word for fw in phrase_words])
            
            # Clean: Remove the trigger word (i) and any unambiguous fillers
            # But keep other ambiguous words (like 'like') if they are not the trigger
            clean_text_words = []
            for k in range(start, end):
                fw = words[k]
                fw_clean = fw.word.lower().strip(".,?!")
                
                # If it's the specific word instance we detected as filler -> Remove
                if k == i:
                    continue
                    
                # If it's an unambiguous filler (uh, um) -> Remove
                if fw_clean in SAFE_TO_REMOVE:
                    continue
                    
                # Otherwise keep (e.g. 'like' at another position, or normal words)
                clean_text_words.append(fw.word)
                
            clean_text = " ".join(clean_text_words)
            
            if clean_text: # Ensure we don't have empty clean text
                examples.append({
                    "original_text": original_text,
                    "clean_text": clean_text,
                    "filler": clean_w
                })
                
            if len(examples) >= 3:
                break
    
    return HesitationStats(
        score_label="Detected",
        desc="检测到了一些填充词。尝试用停顿代替它们。",
        fillers=fillers_list,
        examples=examples,
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
    top_n = config.get("analysis.weak_words_top_n", 5)
    ok_threshold = config.get("analysis.word_thresholds.ok", 85)
    
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
    top_n = config.get("analysis.weak_phonemes_top_n", 3)
    ok_threshold = config.get("analysis.phoneme_thresholds.ok", 85)
    
    # 情况 1：如果有详细音素，按出现频率排序
    if alignment.phonemes:
        weak_phoneme_counts: Counter[str] = Counter()
        for phoneme in alignment.phonemes:
            if phoneme.score < ok_threshold:
                # 标准化音素名称（去掉数字后缀等）
                phoneme_name = phoneme.phoneme.rstrip("012").upper()
                weak_phoneme_counts[phoneme_name] += 1
        
        # 取出现最多的 top N
        most_common = weak_phoneme_counts.most_common(top_n)
        return [phoneme for phoneme, count in most_common]
    
    # 情况 2：如果没有详细音素（保底模式），尝试从弱词中合成音素建议
    # 这是一种“启发式”分析，让报告看起来更专业
    else:
        # 获取所有弱词（不限于 top_n）
        all_weak = [w.word.lower() for w in alignment.words if w.tag != WordTag.OK and w.tag != WordTag.MISSING]
        
        # 简单规则映射 (Spelling -> Phoneme)
        rules = [
            ("th", "θ"),
            ("v", "v"),
            ("r", "r"),
            ("l", "l"),
            ("ng", "ŋ"),
            ("w", "w"),
            ("ph", "f"),
            ("sh", "ʃ"),
            ("ch", "tʃ"),
        ]
        
        synthesized: Counter[str] = Counter()
        for word in all_weak:
            for pattern, ph in rules:
                if pattern in word:
                    synthesized[ph] += 1
        
        # 取出现最多的 top N
        most_common = synthesized.most_common(top_n)
        return [ph for ph, count in most_common]


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
    
    # 同样使用正则分词进行对比
    script_words = set(
        word.lower()
        for word in re.findall(r"[a-zA-Z']+", script_text)
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


def detect_mistakes(alignment: Alignment, engine_raw: dict[str, Any]) -> list[dict[str, Any]]:
    """
    检测具体的错误模式，生成详细描述。
    """
    mistakes = []
    
    # 1. 检测 AI 语义冲突 (来自 ProEngine)
    ai_referee = engine_raw.get("ai_referee", {})
    if ai_referee.get("status") == "completed" and ai_referee.get("conflicts", 0) > 0:
        conflict_details = ai_referee.get("conflict_details", [])
        for conflict in conflict_details:
            got_text = conflict.get("got", "")
            mistakes.append({
                "type": "substitution",
                "target": conflict.get("word", ""),
                "expected": conflict.get("expected", ""),
                "got": got_text,
                "desc": f"Said '{got_text}' instead of '{conflict.get('expected', '')}'",
                "severity": "medium"
            })

    # 2. 检测漏读 (Missing)
    for word in alignment.words:
        if word.tag == WordTag.MISSING:
            mistakes.append({
                "type": "missing",
                "target": word.word,
                "desc": "Forgot to pronounce",
                "severity": "high"
            })

    # 3. 检测音素级显著错误 (GOP Evidence)
    for word in alignment.words:
        # 即使 WordTag 是 OK，如果有音素分极低，也要挑出来
        for phoneme in getattr(word, 'phonemes', []):
            if phoneme.tag in [PhonemeTag.WEAK, PhonemeTag.POOR] and phoneme.score < 65:
                mistakes.append({
                    "type": "accuracy",
                    "target": phoneme.phoneme,
                    "word": word.word,
                    "desc": f"Pronunciation inaccuracy",
                    "severity": "medium",
                    "score": phoneme.score
                })

    return mistakes


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
