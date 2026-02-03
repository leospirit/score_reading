
import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from src.advice.generator import generate_feedback
from src.analysis.llm_advisor import get_llm_advisor
from src.models import (
    EngineMode,
    Meta,
    ScoringResult,
)
from src.pipeline.analyze import analyze_results, assign_tags
from src.pipeline.normalize import normalize_scores
from src.pipeline.engines.whisper_engine import WhisperEngine
from src.pipeline.preprocess import preprocess_audio
from src.pipeline.router import run_with_fallback
from src.report.render_html import render_html_report

logger = logging.getLogger("score_reading")

def run_scoring_pipeline(
    mp3_path: Path,
    text: str,
    output_dir: Path,
    student_id: str = "unknown",
    task_id: str = "default",
    submission_id: Optional[str] = None,
    engine_mode: EngineMode = EngineMode.AUTO,
    progress_callback = None
) -> Tuple[ScoringResult, Path, Path]:
    """
    运行完整的评分 Pipeline
    
    Returns:
        (result, json_path, html_path)
    """
    start_time = time.time()
    
    if not submission_id:
        import hashlib
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
        submission_id = f"sub_{timestamp}_{random_hash}"
        
    # Ensure output dir exists
    final_output_dir = output_dir / task_id / student_id / submission_id
    final_output_dir.mkdir(parents=True, exist_ok=True)
    
    # Init result
    result = ScoringResult()
    result.meta = Meta(
        task_id=task_id,
        student_id=student_id,
        student_name=student_id,
        submission_id=submission_id,
        timestamp=datetime.now().isoformat(),
    )
    result.script_text = text
    result.engine_raw = {}  # Initialize to empty dict to avoid undefined errors

    def update_progress(desc: str):
        if progress_callback:
            progress_callback(desc)
        logger.info(desc)

    try:
        # Use a stable work directory under data for sibling container (DooD) support
        work_base = Path("data/work")
        work_base.mkdir(parents=True, exist_ok=True)
        
        with tempfile.TemporaryDirectory(dir=work_base) as work_dir:
            work_path = Path(work_dir)
            
            # 1. Preprocess
            update_progress("预处理音频...")
            wav_path, audio_metrics = preprocess_audio(mp3_path, work_path)
            result.audio = audio_metrics
            
            # 1.1 Auto-Transcribe if text is empty
            if not text or not text.strip():
                update_progress("正在自动识别朗读文本...")
                whisper = WhisperEngine()
                transcript_words = whisper._transcribe(wav_path)
                text = " ".join([w["word"] for w in transcript_words])
                result.script_text = text
                result.meta.is_auto_transcribed = True
                logger.info(f"自动识别结果: {text}")
            
            # 2. Run Engine
            update_progress("运行评分引擎...")
            alignment, engine_raw, engine_used, fallback_chain = run_with_fallback(
                wav_path=wav_path,
                script_text=text,
                work_dir=work_path,
                engine_mode=engine_mode,
                audio_metrics=audio_metrics,
            )
            
            result.alignment = alignment
            result.engine_raw = engine_raw
            result.meta.engine_used = engine_used
            result.meta.fallback_chain = fallback_chain
            
            # 3. Normalize
            update_progress("计算分数...")
            result.scores = normalize_scores(
                engine_raw=engine_raw,
                audio_metrics=audio_metrics,
                alignment=alignment,
                script_text=text,
            )
            assign_tags(alignment)
            
            # 4. Analyze
            update_progress("分析结果...")
            result.analysis = analyze_results(alignment, text, engine_raw)
            
            # 5. Feedback
            update_progress("生成建议...")
            result.feedback = generate_feedback(result.analysis)
            
            # 5.1 LLM Feedback (Priority: Engine-Native Multimodal Feedback)
            update_progress("AI 老师点评中...")
            try:
                # 检查引擎是否已经提供了深度反馈 (如 Gemini 2.0 原生多模态反馈)
                integrated = (result.engine_raw or {}).get("integrated_feedback")
                
                # 如果引擎已经提供了完整点评 (即 multimodal path)，则直接使用，避免二次调用 LLM 造成质量摊薄
                if integrated and integrated.get("overall_comment"):
                    logger.info("Using engine-native multimodal feedback (High Fidelity Path)")
                    from src.models import Feedback
                    result.feedback = Feedback(
                        cn_summary=integrated.get("overall_comment"),
                        cn_actions=integrated.get("specific_suggestions", []),
                        practice=integrated.get("practice_tips", [])
                    )
                    # 确保 advisor_feedback 也被填充，用于 UI 展现
                    result.advisor_feedback = integrated
                else:
                    # 如果引擎没有集成点评 (如 Wav2Vec2)，则按需调用 Advisor (Slow Path)
                    logger.info("No integrated feedback found, calling LLM Advisor (Standard Path)")
                    advisor = get_llm_advisor()
                    result.feedback, result.advisor_feedback = advisor.generate_feedback(result)
            except Exception as e:
                logger.warning(f"AI 点评失败: {e}")
                # Fallback to a basic message if everything fails
                if not result.feedback:
                     from src.models import Feedback
                     result.feedback = Feedback(cn_summary="评分分析完成，请查收建议。", cn_actions=[], practice=[])
            
            # Finalize
            result.meta.processing_time_ms = int((time.time() - start_time) * 1000)
            
            # 6. Save
            update_progress("保存结果...")
            json_path = final_output_dir / f"{submission_id}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
                
            html_path = final_output_dir / f"{submission_id}.html"
            render_html_report(result, html_path, audio_path=mp3_path)
            
            return result, json_path, html_path

    except Exception as e:
        result.error = str(e)
        result.meta.processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Save error result
        json_path = final_output_dir / f"{submission_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            
        raise e
