"""
口语评分 CLI 框架 - 数据模型定义

定义统一的数据结构，用于在各模块间传递数据。
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EngineMode(str, Enum):
    """评分引擎模式"""
    AUTO = "auto"
    FAST = "fast"
    PRO = "pro"
    WHISPER = "whisper"
    AZURE = "azure"
    GEMINI = "gemini"
    WAV2VEC2 = "wav2vec2"


class WordTag(str, Enum):
    """词级评分标签"""
    OK = "ok"
    WEAK = "weak"
    MISSING = "missing"
    POOR = "poor"


class PhonemeTag(str, Enum):
    """音素级评分标签"""
    OK = "ok"
    WEAK = "weak"
    POOR = "poor"


@dataclass
class AudioMetrics:
    """音频质量指标"""
    duration_sec: float
    silence_ratio: float
    rms_db: float
    clipping_ratio: float = 0.0


@dataclass
class PauseInfo:
    """停顿信息"""
    type: str  # good, bad, optional, missed
    duration: float = 0.0


@dataclass
class WordAlignment:
    """词对齐信息"""
    word: str
    start: float
    end: float
    tag: WordTag = WordTag.OK
    score: float = 100.0
    pause: PauseInfo | None = None  # 单词后的停顿信息
    stress: float = 0.0  # 单词重音强度 (0.0 - 1.0)
    is_linked: bool = False  # 是否与下一个词连读
    expected_stress: float = 0.5  # 期望重音强度 (Native Speaker 参考)
    diagnosis: str = ""  # AI 补充的诊断信息 (例如: "原文识别为 frine")
    phonemes: list["PhonemeAlignment"] = field(default_factory=list) # 音素级对齐详情


@dataclass
class PhonemeAlignment:
    """音素对齐信息"""
    phoneme: str
    start: float
    end: float
    tag: PhonemeTag = PhonemeTag.OK
    score: float = 100.0
    in_word: str = ""


@dataclass
class Alignment:
    """完整对齐信息"""
    words: list[WordAlignment] = field(default_factory=list)
    phonemes: list[PhonemeAlignment] = field(default_factory=list)


@dataclass
class Scores:
    """评分结果（0-100 分制）"""
    overall_100: float = 0.0
    pronunciation_100: float = 0.0
    fluency_100: float = 0.0
    intonation_100: float = 0.0
    completeness_100: float = 0.0


@dataclass
class Confusion:
    """音素混淆记录"""
    expected: str
    got: str
    count: int = 1


@dataclass
class PacePoint:
    """语速数据点 (Time vs WPM)"""
    x: float
    y: int


@dataclass
class PitchPoint:
    """语调数据点 (Time vs F0)"""
    t: float
    f0: float


@dataclass
class HesitationStats:
    """迟疑与口癖分析"""
    score_label: str
    desc: str
    fillers: list[dict] = field(default_factory=list)  # [{"word": "uh", "count": 2}]
    examples: list[dict] = field(default_factory=list) # [{"original": "...", "corrected": "..."}]
    tips: list[str] = field(default_factory=list)


@dataclass
class CompletenessStats:
    """完整度分析"""
    title: str = "Completeness"
    score_label: str = ""
    coverage: int = 0
    missing_stats: dict = field(default_factory=dict) # {total: 3, keywords: 0, function_words: 3}
    insight: str = ""
    tips: list[str] = field(default_factory=list)


@dataclass
class Analysis:
    """分析结果"""
    weak_words: list[str] = field(default_factory=list)
    weak_phonemes: list[str] = field(default_factory=list)
    missing_words: list[str] = field(default_factory=list)
    confusions: list[Confusion] = field(default_factory=list)
    mistakes: list[dict] = field(default_factory=list)  # 具体错误描述
    
    # New Fields for Advanced UI
    pace_chart_data: list[PacePoint] = field(default_factory=list)
    pitch_contour: list[PitchPoint] = field(default_factory=list)  # 语调曲线数据
    hesitations: HesitationStats | None = None
    completeness: CompletenessStats | None = None


@dataclass
class Feedback:
    """反馈建议"""
    cn_summary: str = ""
    cn_actions: list[str] = field(default_factory=list)
    practice: list[str] = field(default_factory=list)


@dataclass
class Meta:
    """元数据"""
    task_id: str = ""
    student_id: str = ""
    student_name: str = ""
    submission_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    engine_used: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    processing_time_ms: int = 0
    is_auto_transcribed: bool = False


@dataclass
class ScoringResult:
    """
    完整评分结果
    
    这是整个评分流程的最终输出，包含所有信息。
    """
    meta: Meta = field(default_factory=Meta)
    audio: AudioMetrics | None = None
    script_text: str = ""
    scores: Scores = field(default_factory=Scores)
    engine_raw: dict[str, Any] = field(default_factory=dict)
    alignment: Alignment = field(default_factory=Alignment)
    analysis: Analysis = field(default_factory=Analysis)
    feedback: Feedback = field(default_factory=Feedback)
    advisor_feedback: dict[str, Any] | None = None  # AI 老师完整点评数据
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式（用于 JSON 输出）"""
        return {
            "meta": {
                "task_id": self.meta.task_id,
                "student_id": self.meta.student_id,
                "student_name": self.meta.student_name,
                "submission_id": self.meta.submission_id,
                "timestamp": self.meta.timestamp,
                "engine_used": self.meta.engine_used,
                "fallback_chain": self.meta.fallback_chain,
                "processing_time_ms": self.meta.processing_time_ms,
                "is_auto_transcribed": self.meta.is_auto_transcribed,
            },
            "audio": {
                "duration_sec": self.audio.duration_sec if self.audio else 0,
                "silence_ratio": self.audio.silence_ratio if self.audio else 0,
                "rms_db": self.audio.rms_db if self.audio else 0,
                "clipping_ratio": self.audio.clipping_ratio if self.audio else 0,
            } if self.audio else None,
            "script_text": self.script_text,
            "scores": {
                "overall_100": round(self.scores.overall_100, 1),
                "pronunciation_100": round(self.scores.pronunciation_100, 1),
                "fluency_100": round(self.scores.fluency_100, 1),
                "intonation_100": round(self.scores.intonation_100, 1),
                "completeness_100": round(self.scores.completeness_100, 1),
            },
            "engine_raw": self.engine_raw,
            "alignment": {
                "words": [
                    {
                        "word": w.word,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "tag": w.tag.value,
                        "score": round(w.score, 1),
                        "pause": {"type": w.pause.type, "duration": w.pause.duration} if w.pause else None,
                        "stress": w.stress,
                        "is_linked": w.is_linked,
                        "diagnosis": w.diagnosis,
                    }
                    for w in self.alignment.words
                ],
                "phonemes": [
                    {
                        "phoneme": p.phoneme,
                        "start": round(p.start, 3),
                        "end": round(p.end, 3),
                        "tag": p.tag.value,
                        "score": round(p.score, 1),
                        "in_word": p.in_word,
                    }
                    for p in self.alignment.phonemes
                ],
            },
            "analysis": {
                "weak_words": self.analysis.weak_words,
                "weak_phonemes": self.analysis.weak_phonemes,
                "missing_words": self.analysis.missing_words,
                "confusions": [
                    {"expected": c.expected, "got": c.got, "count": c.count}
                    for c in self.analysis.confusions
                ],
                "mistakes": self.analysis.mistakes,
                "pace_chart_data": [{"x": p.x, "y": p.y} for p in self.analysis.pace_chart_data],
                "pitch_contour": [{"t": p.t, "f": p.f0} for p in self.analysis.pitch_contour],
                "hesitations": {
                    "score_label": self.analysis.hesitations.score_label,
                    "desc": self.analysis.hesitations.desc,
                    "fillers": self.analysis.hesitations.fillers,
                    "examples": self.analysis.hesitations.examples,
                    "tips": self.analysis.hesitations.tips
                } if self.analysis.hesitations else None,
                "completeness": {
                    "title": self.analysis.completeness.title,
                    "score_label": self.analysis.completeness.score_label,
                    "coverage": self.analysis.completeness.coverage,
                    "missing_stats": self.analysis.completeness.missing_stats,
                    "insight": self.analysis.completeness.insight,
                    "tips": self.analysis.completeness.tips
                } if self.analysis.completeness else None,
            },
            "feedback": {
                "cn_summary": self.feedback.cn_summary,
                "cn_actions": self.feedback.cn_actions,
                "practice": self.feedback.practice,
            },
            "advisor_feedback": self.advisor_feedback,
            "error": self.error,
        }
