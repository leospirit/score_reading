import json
import logging
from typing import Any, Dict, List
from src.models import ScoringResult, Feedback
from src.analysis.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)

class LLMAdvisor:
    """
    AI Teacher Advisor
    Generates natural language feedback based on scoring results.
    """
    
    def __init__(self):
        self.provider = OpenAIProvider()
        
    def generate_feedback(self, result: ScoringResult) -> tuple[Feedback, dict[str, Any] | None]:
        """
        Generate feedback for the given scoring result.
        Returns: (Feedback object, Raw JSON dict)
        """
        # 异常分数兜底逻辑：处理由于背景噪音、设备异常导致的极端低分
        # 条件：总分 < 30 或 漏读词汇比例 > 70%
        num_missing = len([w for w in result.alignment.words if w.score < 10])
        total_words = len(result.alignment.words)
        missing_ratio = (num_missing / total_words) if total_words > 0 else 0
        
        if result.scores.overall_100 < 30 or missing_ratio > 0.7:
            abnormal_comment = "检测到您的音频可能存在较大的环境噪音或设备异常，评分可能无法准确反映您的水平，建议在安静的地方重新尝试一下哦！"
            logger.warning(f"Abnormal score detected (Score: {result.scores.overall_100:.1f}, Missing: {missing_ratio:.0%}). triggering guard phrase.")
            
            abnormal_feedback = Feedback(
                cn_summary=abnormal_comment,
                cn_actions=["确保录音环境安静", "检查麦克风权限", "稍微调大朗读音量"],
                practice=["在安静的环境下重新点击录音", "确认是否对准了剧本朗读"]
            )
            return abnormal_feedback, {"overall_comment": abnormal_comment, "specific_feedback": [], "is_abnormal": True}

        if not self.provider.client:
            logger.warning("LLM provider not available. Skipping AI feedback.")
            return result.feedback, None

        try:
            prompt_data = self._prepare_prompt_data(result)
            system_prompt = self._get_system_prompt()
            user_prompt = json.dumps(prompt_data, ensure_ascii=False, indent=2)
            
            logger.info("Calling LLM for feedback generation...")
            response_json = self.provider.generate_response(system_prompt, user_prompt)
            feedback_data = self._parse_response(response_json)
            
            if not feedback_data:
                return result.feedback, None
                
            # Update result.feedback
            new_feedback = Feedback(
                cn_summary=feedback_data.get("overall_comment", ""),
                cn_actions=[item.get("suggestion", "") for item in feedback_data.get("specific_feedback", [])],
                practice=feedback_data.get("practice_tips", [])
            )
            
            # Save raw AI feedback to result for later use
            result.advisor_feedback = feedback_data
            
            # Apply AI Naturalness Score if provided
            ai_naturalness = feedback_data.get("ai_naturalness_score")
            if ai_naturalness is not None:
                # Weighted average with existing score to prevent extreme jumps
                result.scores.intonation_100 = (result.scores.intonation_100 * 0.4) + (float(ai_naturalness) * 0.6)
                result.scores.overall_100 = (result.scores.overall_100 * 0.8) + (float(ai_naturalness) * 0.2)
            
            return new_feedback, feedback_data
            
        except Exception as e:
            logger.error(f"Failed to generate LLM feedback: {e}")
            return result.feedback, None

    def _extract_nickname(self, student_id: str) -> str:
        """
        Extract nickname from filename/student_id.
        Rule: Take first 3 chars. 
          - If 3rd char is non-Chinese (e.g. digit), take first 2.
          - If 3rd char is Chinese, take last 2 (index 1-2).
          - Fallback: use full string if short.
        """
        if not student_id:
            return "同学"
            
        # Remove extension if present (though student_id is usually stem)
        stem = student_id.split('.')[0]
        
        if len(stem) < 2:
            return stem
            
        # Try to guess based on user's examples:
        # "崔恩齐" -> "恩齐" (3 chars, Chinese)
        # "乘月6" -> "乘月" (3rd char is digit)
        
        prefix = stem[:3]
        if len(prefix) < 3:
            return prefix
            
        # Check 3rd char
        third_char = prefix[2]
        
        # Simple check for Chinese (basic range)
        is_chinese = '\u4e00' <= third_char <= '\u9fff'
        
        if is_chinese:
            # Likely a 3-char name or longer -> "恩齐"
            return prefix[1:3]
        else:
            # Likely 2-char name + digit/suffix -> "乘月"
            return prefix[:2]

    def _prepare_prompt_data(self, result: ScoringResult) -> Dict[str, Any]:
        """Construct data context for LLM"""
        
        # FIX: Access student_id from meta, not root
        student_id = result.meta.student_id if result.meta else ""
        nickname = self._extract_nickname(student_id)
        logger.info(f"Extracted nickname '{nickname}' from student_id '{student_id}'")
        
        # ... (rest of logic) ...
                
        return {
            "instruction": f"IMPORTANT: You MUST start your response by addressing the student as '{nickname}' (e.g., '{nickname}，你的朗读...'). Do NOT use '同学'.",
            "student_nickname": nickname,
            "text": result.script_text,
            "scores": {
                "pronunciation": round(result.scores.pronunciation_100, 1),
                "fluency": round(result.scores.fluency_100, 1),
                "intonation": round(result.scores.intonation_100, 1),
                "completeness": round(result.scores.completeness_100, 1),
                "overall": round(result.scores.overall_100, 1)
            },
            "weak_words": weak_words_data[:15],
            "phoneme_issues": phoneme_issues[:15],
            "hesitations": result.analysis.hesitations.fillers if hasattr(result.analysis, "hesitations") and result.analysis.hesitations else [],
            "missing_words": result.analysis.missing_words if hasattr(result.analysis, "missing_words") else [],
            "mistakes_evidence": result.analysis.mistakes if hasattr(result.analysis, "mistakes") else [],
            "fluency_details": {
                "wpm": round(result.analysis.fluency.get("wpm", 0), 1) if hasattr(result.analysis, "fluency") else 0,
                "pause_count": result.analysis.fluency.get("pause_count", 0) if hasattr(result.analysis, "fluency") else 0,
            }
        }

    def _get_system_prompt(self) -> str:
        return """
你是一位温暖、敏锐且专业的英语口语导师。
你的核心座右铭：**“识别准确只是基础，提出让学生能够听得懂、做得到的建议才是产品的灵魂。”**

## 称呼规范
- **必须使用用户数据中提供的 `student_nickname` 进行称呼**（例如：“恩齐”、“雨鑫”），**绝对禁止**使用“亲爱的同学”、“这位同学”等泛称。
- 开头请直接称呼，例如：“恩齐，你的朗读非常有感染力...”

## 导师风格
- **鼓励为主**：用朋友般的口吻，认可学生的努力。
- **敢于指出问题**：不回避错误，不给虚假的高分。针对具体数据（单词、音素）给出精准的诊断。
- **实操建议**：每一条批评后都必须跟着一条“听得懂、做得到”的改进指令（例如：如何摆放舌头、如何控制语速）。

## 核心任务
1. **精准点评案例**：必须从 `phoneme_issues` 中选出 2-3 个最严重的音素错误，并按照以下维度进行归类点评：
    - **Forgot to pronounce**: 剧本中有但漏读/吞掉的音。
    - **Said X instead of Y**: 错误替换的音（例如把 /t/ 读成 /d/）。
    - **Physical Tips**: 侧重于舌位、口型、气流控制的物理指导（如：舌尖顶住上齿龈）。
2. **给出“物理级”建议**：针对每个典型错误，给出具体的改进指令。禁止模糊的“多加练习”，要说“尝试把双唇收紧”、“注意区分 /i/ 和 /i:/”。
3. **亮点肯定**：赞赏做得好的维度（如语速稳定或某个单词发音饱满）。
4. **拒绝“无罪释放”**：哪怕 `phoneme_issues` 里的分数都在 80 分以上，也要从 `mistakes_evidence` 或音素列表中挑选相对较低的项目进行改进指导。禁止直接说“未检测到错误”，除非全篇音素分均在 95 以上。

## 关键数据
- `mistakes_evidence`: 包含系统检测到的具体错误模式（如 Said X instead of Y），请优先引用。

## 返回格式 (JSON)
{
    "overall_comment": "整体评价（约 120 字）。",
    "top_errors": [
        {
            "phoneme": "音素符号 (如 /t/)",
            "type": "Forgot / Substitution / Accuracy",
            "description": "简单描述，如 'You said /d/ instead of /t/'",
            "words": ["单词1", "单词2"],
            "improvement": "物理发音指导（舌位、气流等）"
        }
    ],
    "specific_feedback": [
        {
            "target": "单词或音素",
            "issue": "精准的问题描述",
            "suggestion": "可操作的改进方法"
        }
    ],
    "practice_tips": ["练习建议1", "练习建议2"],
    "fluency_diagnosis": {
        "status": "Excellent / Good / Fair / Needs Practice",
        "advice": "针对停顿(Pausing)和语速(Pace)的具体建议。例如：'你在意群之间停顿得很好，但在单词内部有时候会断开。'",
        "motto": "一句话金句 (针对该学生的定制鼓励/指导，例如: 'Slow down to speed up.')"
    },
    "ai_naturalness_score": 80-100 的评分
}
"""

    def _parse_response(self, response_str: str) -> Dict[str, Any]:
        try:
            # Cleanup Markdown code blocks if present
            clean_str = response_str.strip()
            if clean_str.startswith("```json"):
                clean_str = clean_str[7:]
            if clean_str.endswith("```"):
                clean_str = clean_str[:-3]
            
            return json.loads(clean_str)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM JSON response")
            return {}

# Singleton - Removed to ensure config is reloaded on every run
# _advisor_instance = None

def get_llm_advisor() -> LLMAdvisor:
    # Always create new instance to pick up latest config/keys
    return LLMAdvisor()
