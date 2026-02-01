"""
口语评分 CLI 框架 - 建议生成模块

基于音素规则库生成可执行的发音改进建议。
"""
import logging
from pathlib import Path
from typing import Any

import yaml

from src.models import Analysis, Feedback

logger = logging.getLogger(__name__)

# 规则库路径
RULES_PATH = Path(__file__).parent.parent.parent / "advice" / "phoneme_rules.yaml"

# 缓存的规则库
_rules_cache: dict[str, Any] | None = None


def load_rules() -> dict[str, Any]:
    """
    加载音素规则库
    
    Returns:
        规则库数据
    """
    global _rules_cache
    
    if _rules_cache is not None:
        return _rules_cache
    
    if not RULES_PATH.exists():
        logger.warning(f"规则库不存在: {RULES_PATH}")
        _rules_cache = {"rules": [], "fallback_advice": {}}
        return _rules_cache
    
    with open(RULES_PATH, encoding="utf-8") as f:
        _rules_cache = yaml.safe_load(f) or {"rules": [], "fallback_advice": {}}
    
    logger.info(f"已加载规则库，共 {len(_rules_cache.get('rules', []))} 条规则")
    return _rules_cache


def find_phoneme_rule(phoneme: str) -> dict[str, Any] | None:
    """
    查找音素对应的规则
    
    Args:
        phoneme: 音素名称（如 TH, R, L）
        
    Returns:
        规则字典，如果找不到返回 None
    """
    rules = load_rules()
    phoneme_upper = phoneme.upper().rstrip("012")
    
    for rule in rules.get("rules", []):
        if rule.get("phoneme", "").upper() == phoneme_upper:
            return rule
    
    return None


def generate_feedback(analysis: Analysis) -> Feedback:
    """
    生成改进建议
    
    基于分析结果中的 weak_phonemes 和 confusions 生成建议。
    
    Args:
        analysis: 分析结果
        
    Returns:
        反馈建议
    """
    logger.info("开始生成改进建议")
    
    feedback = Feedback()
    rules = load_rules()
    
    # 收集需要生成建议的音素
    target_phonemes: list[str] = []
    
    # 优先使用 confusions
    for confusion in analysis.confusions[:2]:
        if confusion.expected and confusion.expected not in target_phonemes:
            target_phonemes.append(confusion.expected)
    
    # 补充使用 weak_phonemes
    for phoneme in analysis.weak_phonemes:
        if phoneme not in target_phonemes:
            target_phonemes.append(phoneme)
            if len(target_phonemes) >= 2:
                break
    
    if not target_phonemes:
        # 没有识别到具体问题音素，使用通用建议
        fallback = rules.get("fallback_advice", {})
        feedback.cn_summary = fallback.get("cn_summary", "继续保持练习！")
        feedback.cn_actions = fallback.get("cn_actions", [])
        feedback.practice = fallback.get("practice", [])
        return feedback
    
    # 生成针对性建议
    summaries: list[str] = []
    actions: list[str] = []
    practices: list[str] = []
    
    for phoneme in target_phonemes:
        rule = find_phoneme_rule(phoneme)
        
        if rule:
            # 添加发音提示到摘要
            cn_tip = rule.get("cn_tip", "")
            if cn_tip:
                summaries.append(f"{phoneme} 音: {cn_tip}")
            
            # 添加练习步骤
            practice_steps = rule.get("practice_steps", [])
            for step in practice_steps[:2]:  # 每个音素取前 2 个步骤
                if step not in actions:
                    actions.append(step)
            
            # 添加 minimal pairs
            minimal_pairs = rule.get("minimal_pairs", [])
            for pair in minimal_pairs[:2]:  # 每个音素取前 2 对
                if isinstance(pair, list) and len(pair) >= 2:
                    pair_str = f"{pair[0]} / {pair[1]}"
                    if pair_str not in practices:
                        practices.append(pair_str)
    
    # 生成摘要
    if summaries:
        feedback.cn_summary = "；".join(summaries[:2])
    else:
        feedback.cn_summary = f"建议重点练习以下发音: {', '.join(target_phonemes)}"
    
    # 限制建议数量
    feedback.cn_actions = actions[:3]  # 最多 3 条建议
    feedback.practice = practices[:4]  # 最多 4 对 minimal pairs
    
    # 如果没有足够的建议，补充通用建议
    fallback = rules.get("fallback_advice", {})
    
    if len(feedback.cn_actions) < 2:
        for action in fallback.get("cn_actions", []):
            if action not in feedback.cn_actions:
                feedback.cn_actions.append(action)
                if len(feedback.cn_actions) >= 3:
                    break
    
    logger.info(
        f"建议生成完成: 摘要长度={len(feedback.cn_summary)}, "
        f"建议数={len(feedback.cn_actions)}, "
        f"练习词数={len(feedback.practice)}"
    )
    
    return feedback


def generate_feedback_for_confusions(
    confusions: list[tuple[str, str, int]]
) -> list[str]:
    """
    为特定的音素混淆生成针对性建议
    
    Args:
        confusions: 混淆列表 [(expected, got, count), ...]
        
    Returns:
        建议列表
    """
    tips: list[str] = []
    
    for expected, got, count in confusions:
        rule = find_phoneme_rule(expected)
        
        if rule:
            # 检查 got 是否在 common_confusions 中
            common_confusions = rule.get("common_confusions", [])
            
            if got.upper() in [c.upper() for c in common_confusions]:
                cn_tip = rule.get("cn_tip", "")
                if cn_tip:
                    tips.append(
                        f"你把 {expected} 发成了 {got}（出现 {count} 次）。"
                        f"正确发音方法: {cn_tip}"
                    )
    
    return tips
