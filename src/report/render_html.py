"""
口语评分 CLI 框架 - HTML 报告渲染模块

负责将评分结果渲染为 HTML 报告。
支持音频波形嵌入和交互播放。
"""
import base64
import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.config import config
from src.models import ScoringResult

logger = logging.getLogger(__name__)

# 模板目录
TEMPLATES_DIR = Path(__file__).parent / "templates"

# 发音指导规则
PHONEME_TIPS = {
    "θ": {
        "name": "无声齿擦音",
        "examples": ["three", "think", "thank"],
        "advice": "舌尖轻触上齿，气流从舌尖与上齿间隙中通过。可以用镜子检查舌尖是否可见。"
    },
    "ð": {
        "name": "有声齿擦音",
        "examples": ["the", "this", "that"],
        "advice": "与 /θ/ 相似，但需要振动声带。舌尖轻触上齿，同时发出'嗡嗡'声。"
    },
    "r": {
        "name": "卷舌音",
        "examples": ["red", "run", "right"],
        "advice": "舌尖向后卷曲，不要接触口腔任何部位。嘴唇略微圆起。"
    },
    "l": {
        "name": "舌边音",
        "examples": ["like", "love", "light"],
        "advice": "舌尖顶住上齿龈，气流从舌头两侧通过。结尾的 /l/ 需要把舌尖顶住，不要省略。"
    },
    "v": {
        "name": "唇齿擦音",
        "examples": ["very", "have", "love"],
        "advice": "上齿轻轻咬住下唇，振动声带。注意不要发成 /w/。"
    },
    "w": {
        "name": "圆唇半元音",
        "examples": ["we", "what", "water"],
        "advice": "嘴唇收圆，像吹口哨的嘴形，然后快速过渡到后面的元音。"
    },
    "ŋ": {
        "name": "后鼻音",
        "examples": ["sing", "thing", "king"],
        "advice": "舌根抬起接触软腭，气流从鼻腔通过。不要在结尾加 /g/ 的音。"
    },
    "æ": {
        "name": "开前元音",
        "examples": ["cat", "bad", "apple"],
        "advice": "嘴巴张大，舌头放平并尽量往前，嘴角略微拉开。比中文的'啊'嘴巴张得更大。"
    },
}


def encode_audio_base64(audio_path: Path) -> str | None:
    """
    将音频文件编码为 base64
    
    Args:
        audio_path: 音频文件路径
        
    Returns:
        base64 编码字符串，或 None（如果文件不存在）
    """
    if not audio_path or not audio_path.exists():
        return None
    
    try:
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        return base64.b64encode(audio_data).decode("utf-8")
    except Exception as e:
        logger.warning(f"无法编码音频文件: {e}")
        return None


def get_phoneme_tips(weak_phonemes: list[str]) -> list[dict[str, Any]]:
    """
    根据弱音素列表获取发音指导
    
    Args:
        weak_phonemes: 弱音素列表
        
    Returns:
        发音指导列表
    """
    tips = []
    seen = set()
    
    for phoneme in weak_phonemes:
        # 清理音素符号
        clean_phoneme = phoneme.strip("/[]").lower()
        
        # 查找匹配的指导
        for key, tip in PHONEME_TIPS.items():
            if key.lower() in clean_phoneme or clean_phoneme in key.lower():
                if key not in seen:
                    tips.append({
                        "phoneme": key,
                        "name": tip["name"],
                        "examples": tip["examples"],
                        "advice": tip["advice"],
                    })
                    seen.add(key)
    
    return tips


def generate_pronunciation_analysis(
    weak_words: list[str],
    weak_phonemes: list[str],
    phoneme_alignments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    生成发音问题分析数据
    
    当有详细的音素对齐数据时，基于该数据生成分析；
    否则基于 weak_phonemes 和 weak_words 生成分析。
    
    Args:
        weak_words: 弱词列表
        weak_phonemes: 弱音素列表
        phoneme_alignments: 音素对齐数据（包含 in_word 字段）
        
    Returns:
        发音问题分析列表，用于模板渲染
    """
    analysis = []
    
    # 扩展的音素信息映射（包括大小写变体）
    phoneme_tips_extended = {
        # 原始键
        **PHONEME_TIPS,
        # 小写变体
        "æ": PHONEME_TIPS.get("æ", {"name": "开前元音 æ", "advice": "嘴巴张大，舌头放平并往前。"}),
        "ɛ": {"name": "中前元音 ɛ", "advice": "嘴巴半开，舌头中位靠前。类似中文'诶'但更放松。"},
        "ɪ": {"name": "短元音 ɪ", "advice": "嘴巴微开，舌头高位靠前。类似中文'衣'但更短促。"},
        "ɔ": {"name": "中后元音 ɔ", "advice": "嘴巴半开，舌头中位靠后。类似中文'哦'但嘴型更圆。"},
        # 大写变体（用于匹配 Whisper 输出）
        "Æ": {"name": "开前元音 æ", "advice": "嘴巴张大，舌头放平并往前。"},
        "Ɛ": {"name": "中前元音 ɛ", "advice": "嘴巴半开，舌头中位靠前。类似中文'诶'但更放松。"},
    }
    
    # 1. 优先使用详细的音素对齐数据
    if phoneme_alignments:
        # 按音素分组
        phoneme_groups: dict[str, list[str]] = {}
        for pa in phoneme_alignments:
            phoneme = pa.get("phoneme", "")
            in_word = pa.get("in_word", "")
            if phoneme and in_word:
                if phoneme not in phoneme_groups:
                    phoneme_groups[phoneme] = []
                if in_word not in phoneme_groups[phoneme]:
                    phoneme_groups[phoneme].append(in_word)
        
        # 为每个音素生成分析
        for phoneme, words in list(phoneme_groups.items())[:3]:
            phoneme_info = phoneme_tips_extended.get(phoneme) or phoneme_tips_extended.get(phoneme.lower())
            if phoneme_info:
                analysis.append({
                    "target": phoneme,
                    "name": phoneme_info.get("name", f"音素 {phoneme}"),
                    "mistakes": [{
                        "actual": "发音需改进",
                        "desc": phoneme_info.get("advice", "注意发音位置和气流控制。"),
                        "words": [{"text": w, "ipa": f"/{phoneme}/"} for w in words[:4]],
                    }],
                })
    
    # 2. 如果没有详细数据，使用 weak_phonemes 列表
    if not analysis and weak_phonemes:
        for phoneme in weak_phonemes[:3]:
            # 尝试匹配音素（大小写不敏感）
            phoneme_info = phoneme_tips_extended.get(phoneme) or phoneme_tips_extended.get(phoneme.lower())
            if phoneme_info:
                # 找出可能相关的弱词
                related_words = []
                for word in weak_words:
                    related_words.append({"text": word, "ipa": f"/{phoneme}/"})
                    if len(related_words) >= 4:
                        break
                
                analysis.append({
                    "target": phoneme,
                    "name": phoneme_info.get("name", f"音素 {phoneme}"),
                    "mistakes": [{
                        "actual": "发音需练习",
                        "desc": phoneme_info.get("advice", "注意发音位置和气流控制。"),
                        "words": related_words if related_words else [{"text": "(无示例词)", "ipa": ""}],
                    }],
                })
    
    # 3. 最后回退：如果没有音素分析但有弱词
    if not analysis and weak_words:
        # 尝试从弱词中提取一些常见的音素挑战（简单规则）
        challenges = []
        for word in weak_words:
            w_lower = word.lower()
            if 'th' in w_lower: challenges.append("θ/ð")
            if 'v' in w_lower: challenges.append("v")
            if 'l' in w_lower: challenges.append("l")
            if 'r' in w_lower: challenges.append("r")
            if 'ng' in w_lower: challenges.append("ŋ")
        
        # 提取独特的挑战
        unique_challenges = list(dict.fromkeys(challenges))[:2]
        challenge_desc = f"重点关注音素: {', '.join(unique_challenges)}" if unique_challenges else "整体发音清晰度"

        analysis.append({
            "target": "📖",
            "name": "重点词汇练习",
            "is_fallback": True,
            "mistakes": [{
                "actual": challenge_desc,
                "desc": "以下单词的发音得分较低，建议反复跟读，特别注意元音的饱满度和辅音的清晰度。",
                "words": [{"text": w, "ipa": ""} for w in weak_words[:5]],
            }],
        })
    
    return analysis


def render_html_report(
    result: ScoringResult,
    output_path: Path,
    audio_path: Path | None = None,
) -> None:
    """
    渲染 HTML 报告
    
    Args:
        result: 评分结果
        output_path: 输出文件路径
        audio_path: 音频文件路径（用于嵌入播放）
    """
    logger.info(f"开始渲染 HTML 报告: {output_path}")
    
    # 加载模板
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html.j2")
    
    # 获取颜色配置
    colors = {
        "ok": config.get("report.colors.ok", "#4CAF50"),
        "weak": config.get("report.colors.weak", "#FFC107"),
        "missing": config.get("report.colors.missing", "#F44336"),
        "poor": config.get("report.colors.poor", "#E91E63"),
    }
    
    # 准备模板数据
    # 将 WordAlignment 转换为模板可用的字典格式（包含时间戳和高级属性）
    alignment_words = []
    for word in result.alignment.words:
        word_data = {
            "word": word.word,
            "score": word.score,
            "tag": word.tag.value,
            "start": word.start,
            "end": word.end,
            "stress": word.stress,
            "expected_stress": word.expected_stress,
            "is_linked": word.is_linked,
        }
        # 如果存在 Pause 信息，转换为字典
        if word.pause:
            word_data["pause"] = {
                "type": word.pause.type, # 假设是字符串或 Enum.value
                "duration": word.pause.duration
            }
        alignment_words.append(word_data)
    
    # 编码音频为 base64
    audio_base64 = encode_audio_base64(audio_path) if audio_path else None
    
    # 获取发音指导
    phoneme_tips = get_phoneme_tips(result.analysis.weak_phonemes or [])
    
    # 提取 Hesitations 数据
    hesitations_data = None
    if result.analysis.hesitations:
        hesitations_data = {
            "score_label": result.analysis.hesitations.score_label,
            "desc": result.analysis.hesitations.desc,
            "fillers": result.analysis.hesitations.fillers,
            "examples": result.analysis.hesitations.examples,
            "tips": result.analysis.hesitations.tips
        }
        
    # 提取 Completeness 数据
    completeness_data = None
    if result.analysis.completeness:
        completeness_data = {
            "title": result.analysis.completeness.title,
            "score_label": result.analysis.completeness.score_label,
            "coverage": result.analysis.completeness.coverage,
            "missing_stats": result.analysis.completeness.missing_stats,
            "insight": result.analysis.completeness.insight,
            "tips": result.analysis.completeness.tips
        }

    # 提取 Pace Chart 数据
    pace_chart_data = [{"x": p.x, "y": p.y} for p in result.analysis.pace_chart_data]

    template_data = {
        "meta": {
            "task_id": result.meta.task_id,
            "student_id": result.meta.student_id,
            "student_name": result.meta.student_name,
            "submission_id": result.meta.submission_id,
            "timestamp": result.meta.timestamp,
            "engine_used": result.meta.engine_used,
        },
        "scores": {
            "overall_100": result.scores.overall_100,
            "pronunciation_100": result.scores.pronunciation_100,
            "fluency_100": result.scores.fluency_100,
            "intonation_100": result.scores.intonation_100,
            "completeness_100": result.scores.completeness_100,
        },
        "alignment": {
            "words": alignment_words,
        },
        "analysis": {
            "weak_words": result.analysis.weak_words,
            "weak_phonemes": result.analysis.weak_phonemes,
            "missing_words": result.analysis.missing_words,
            "mistakes": result.analysis.mistakes,
        },
        "pronunciation_analysis": generate_pronunciation_analysis(
            result.analysis.weak_words,
            result.analysis.weak_phonemes,
            [p.to_dict() if hasattr(p, "to_dict") else vars(p) for p in result.alignment.phonemes]
        ),
        "hesitations": hesitations_data,
        "completeness_analysis": completeness_data,
        "pace_chart_data": pace_chart_data,
        "pitch_contour": [{"t": p.t, "f": p.f0} for p in result.analysis.pitch_contour],
        "feedback": {
            "cn_summary": result.feedback.cn_summary,
            "cn_actions": result.feedback.cn_actions,
            "practice": result.feedback.practice,
        },
        "feedback": {
            "cn_summary": result.feedback.cn_summary,
            "cn_actions": result.feedback.cn_actions,
            "practice": result.feedback.practice,
        },
        "advisor_feedback": result.advisor_feedback,
        "colors": colors,
        "audio_base64": audio_base64,
        "phoneme_tips": phoneme_tips,
        "pronunciation_analysis": generate_pronunciation_analysis(
            result.analysis.weak_words or [],
            result.analysis.weak_phonemes or [],
            [{"phoneme": p.phoneme, "in_word": p.in_word, "score": p.score} 
             for p in result.alignment.phonemes] if result.alignment.phonemes else None,
        ),
        "engine_raw": result.engine_raw,
        # 优先使用音频文件名，如果没有则使用输出文件名，最后回退到 unknown
        "audio_stem": audio_path.stem if audio_path else (output_path.stem if output_path else "Unknown"),
    }
    
    # 渲染 HTML
    html_content = template.render(**template_data)
    
    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 写入文件
    output_path.write_text(html_content, encoding="utf-8")
    
    logger.info(f"HTML 报告已生成: {output_path}")


def regenerate_report_from_json(json_path: Path, output_path: Path) -> None:
    """
    从 JSON 文件重新生成 HTML 报告
    
    Args:
        json_path: JSON 结果文件路径
        output_path: 输出 HTML 文件路径
    """
    import json
    
    if not json_path.exists():
        raise FileNotFoundError(f"JSON 文件不存在: {json_path}")
    
    # 加载 JSON
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    
    # 加载模板
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html.j2")
    
    # 获取颜色配置
    colors = {
        "ok": config.get("report.colors.ok", "#4CAF50"),
        "weak": config.get("report.colors.weak", "#FFC107"),
        "missing": config.get("report.colors.missing", "#F44336"),
        "poor": config.get("report.colors.poor", "#E91E63"),
    }
    
    # 添加颜色到数据
    data["colors"] = colors
    
    # 获取发音指导
    weak_phonemes = data.get("analysis", {}).get("weak_phonemes", [])
    data["phoneme_tips"] = get_phoneme_tips(weak_phonemes or [])
    
    # 确保没有 audio_base64（从 JSON 重新生成时不嵌入音频）
    if "audio_base64" not in data:
        data["audio_base64"] = None

    # 确保 advisor_feedback 存在
    if "advisor_feedback" not in data:
        data["advisor_feedback"] = None

    # 确保 engine_raw 存在 (解决 UndefinedError)
    if "engine_raw" not in data:
        data["engine_raw"] = {}
    
    # 渲染 HTML
    html_content = template.render(**data)
    
    # 写入文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    
    logger.info(f"HTML 报告已重新生成: {output_path}")

