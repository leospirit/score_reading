import os
import sys
import logging
import json
from typing import Any, Dict, Optional
from pathlib import Path

# Fix import path to prioritize backend src (inside score_reading) over frontend src
# This is crucial because both have a 'src' folder
sys.path.insert(0, str(Path(__file__).parent / "score_reading"))

from fastapi import FastAPI, HTTPException, Body, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import config, load_config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# Init Config
load_config()

app = FastAPI(title="Score Reading API")

# CORS for dev (Frontend runs on port 5173 usually)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AzureConfig(BaseModel):
    api_key: Optional[str] = None
    region: Optional[str] = None

class GeminiConfig(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None

class LLMConfig(BaseModel):
    provider: str
    base_url: Optional[str] = None
    model: str
    api_key: Optional[str] = None

class ConfigUpdate(BaseModel):
    llm: Optional[LLMConfig] = None
    azure: Optional[AzureConfig] = None
    gemini: Optional[GeminiConfig] = None

# --- Async Job System ---
import asyncio
from enum import Enum
from typing import Optional

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Job(BaseModel):
    id: str
    status: JobStatus
    submission_id: str
    student_id: str
    task_id: str
    filename: str
    timestamp: float
    mode: Optional[str] = "auto"  # Added persistence for mode
    result_url: Optional[str] = None
    error: Optional[str] = None
    
# Global State
JOBS: Dict[str, Job] = {}
JOB_QUEUE: asyncio.Queue = asyncio.Queue()
JOBS_FILE = Path("data/jobs.json")
REPORTS_DIR = Path("data/out") # Ensure this is defined for worker usage or import it

def save_jobs():
    """Persist jobs to disk"""
    try:
        data = {k: v.dict() for k, v in JOBS.items()}
        # Ensure directory exists
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(JOBS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save jobs: {e}")

def load_jobs():
    """Load jobs from disk"""
    global JOBS
    if not JOBS_FILE.exists():
        return
    
    try:
        with open(JOBS_FILE, "r") as f:
            data = json.load(f)
            for k, v in data.items():
                try:
                    # Restore Job object
                    job = Job(**v)
                    # If job was PROCESSING when server died, mark it FAILED
                    if job.status == JobStatus.PROCESSING:
                        job.status = JobStatus.FAILED
                        job.error = "Server restarted during processing"
                    JOBS[k] = job
                except Exception as e:
                    logger.warning(f"Skipping invalid job record {k}: {e}")
        logger.info(f"Loaded {len(JOBS)} jobs from disk")
    except Exception as e:
        logger.error(f"Failed to load jobs: {e}")

async def worker():
    """Background worker to process jobs from the queue"""
    logger.info("Worker started")
    while True:
        try:
            job_id, file_path, text, mode, metadata = await JOB_QUEUE.get()
            
            # Update status to PROCESSING
            if job_id in JOBS:
                JOBS[job_id].status = JobStatus.PROCESSING
                save_jobs() # Save state
                logger.info(f"Processing job {job_id} ({metadata['submission_id']})")
                
            try:
                # Run Pipeline (Blocking CPU task, run in threadpool)
                from src.pipeline.runner import run_scoring_pipeline
                from fastapi.concurrency import run_in_threadpool
                
                # Execute pipeline in threadpool to not block async loop
                result, json_path, html_path = await run_in_threadpool(
                    run_scoring_pipeline,
                    mp3_path=file_path,
                    text=text,
                    output_dir=REPORTS_DIR,
                    student_id=metadata['student_id'],
                    task_id=metadata['task_id'],
                    submission_id=metadata['submission_id'],
                    engine_mode=metadata['engine_mode']
                )
                
                # Success
                if job_id in JOBS:
                    JOBS[job_id].status = JobStatus.COMPLETED
                    # Construct simplified report URL
                    rel_path = html_path.relative_to(REPORTS_DIR)
                    JOBS[job_id].result_url = f"/reports/{rel_path}"
                    save_jobs() # Save state
                    logger.info(f"Job {job_id} completed")
                    
            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}")
                if job_id in JOBS:
                    JOBS[job_id].status = JobStatus.FAILED
                    JOBS[job_id].error = str(e)
                    save_jobs() # Save state
            
            finally:
                JOB_QUEUE.task_done()
                
        except asyncio.CancelledError:
            logger.info("Worker cancelled")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(1)

@app.on_event("startup")
async def startup_event():
    # Load concurrency config
    load_config()
    num_workers = config.get("concurrency.default_jobs", 4)
    logger.info(f"Starting {num_workers} background workers...")
    
    # Load persistence
    load_jobs()
    
    # Restoring Queued Jobs
    from src.models import EngineMode
    count_restored = 0
    
    for job_id, job in JOBS.items():
        if job.status == JobStatus.QUEUED:
            # Reconstruct paths
            # Assuming standard path structure: data/uploads/YYYYMMDD/{submission_id}.mp3
            # We can try to find the file.
            # Since timestamp is float, we might not have exact date str easily unless we stored it.
            # BUT, we can search for the file in data/uploads/**/*.mp3 with matching submission_id
            
            found_mp3 = None
            found_txt = "" # Default empty
            
            upload_base = Path("data/uploads")
            if upload_base.exists():
                # Fast search: iterate dates folders?
                # Or just glob
                candidates = list(upload_base.glob(f"**/{job.submission_id}.mp3"))
                if candidates:
                    found_mp3 = candidates[0]
                    # Check for .txt sidecar
                    txt_path = found_mp3.with_suffix(".txt")
                    if txt_path.exists():
                        try:
                            found_txt = txt_path.read_text(encoding="utf-8")
                        except:
                            pass
            
            if found_mp3:
                # Re-queue
                try:
                    target_mode = EngineMode(job.mode.lower()) if job.mode else EngineMode.AUTO
                except:
                    target_mode = EngineMode.AUTO

                metadata = {
                    "student_id": job.student_id,
                    "task_id": job.task_id,
                    "submission_id": job.submission_id,
                    "engine_mode": target_mode
                }
                
                await JOB_QUEUE.put((job_id, found_mp3, found_txt, job.mode or "auto", metadata))
                count_restored += 1
                logger.info(f"Restored queued job {job_id} to execution queue.")
            else:
                logger.warning(f"Could not restore job {job_id}: File not found.")
                # Mark as failed?
                job.status = JobStatus.FAILED
                job.error = "File lost during restart"
                
    if count_restored > 0:
        logger.info(f"Restored {count_restored} jobs from persistence.")
        save_jobs() # Save any failed updates

    for i in range(num_workers):
        asyncio.create_task(worker())

@app.get("/api/config")
def get_config():
    """Get current config (masking API key)"""
    # Reload to get latest
    load_config()
    
    llm_conf = config.get("llm", {})
    azure_conf = config.get("engines.azure", {})
    gemini_conf = config.get("engines.gemini", {})
    
    def mask_key(key):
        if not key: return ""
        if len(key) > 6: return f"{key[:3]}...{key[-3:]}"
        return "***"
        
    return {
        "llm": {
            "provider": llm_conf.get("provider", "openai"),
            "base_url": llm_conf.get("base_url", ""),
            "model": llm_conf.get("model", "gpt-4o"),
            "api_key_masked": mask_key(llm_conf.get("api_key", "")),
            "has_key": bool(llm_conf.get("api_key"))
        },
        "azure": {
            "region": azure_conf.get("region", "eastus"),
            "api_key_masked": mask_key(azure_conf.get("api_key", "")),
            "has_key": bool(azure_conf.get("api_key"))
        },
        "gemini": {
            "model": gemini_conf.get("model", "gemini-1.5-flash"),
            "api_key_masked": mask_key(gemini_conf.get("api_key", "")),
            "has_key": bool(gemini_conf.get("api_key"))
        }
    }

@app.post("/api/config")
def update_config(data: ConfigUpdate):
    updates = data.dict(exclude_unset=True)
    logger.info(f"Received config update: {updates.keys()}")

    save_updates = {}

    # 1. LLM
    if "llm" in updates:
        llm_update = updates["llm"]
        clean_llm = {k: v for k, v in llm_update.items() if k != "api_key"}
        if llm_update.get("api_key") and "***" not in llm_update["api_key"]:
            clean_llm["api_key"] = llm_update["api_key"]
        save_updates["llm"] = clean_llm

    # 2. Azure
    if "azure" in updates:
        az_update = updates["azure"]
        clean_az = {k: v for k, v in az_update.items() if k != "api_key"}
        if az_update.get("api_key") and "***" not in az_update["api_key"]:
            clean_az["api_key"] = az_update["api_key"]
        save_updates["engines"] = save_updates.get("engines", {})
        save_updates["engines"]["azure"] = clean_az

    # 3. Gemini
    if "gemini" in updates:
        gm_update = updates["gemini"]
        clean_gm = {k: v for k, v in gm_update.items() if k != "api_key"}
        if gm_update.get("api_key") and "***" not in gm_update["api_key"]:
            clean_gm["api_key"] = gm_update["api_key"]
        save_updates["engines"] = save_updates.get("engines", {})
        save_updates["engines"]["gemini"] = clean_gm
        
    if save_updates:
        try:
            config.save_user_config(save_updates)
            return {"status": "ok", "message": "Configuration saved"}
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    return {"status": "ok", "message": "No changes detected"}

# Serve Reports (e.g. data/out/demo/demo_report.html -> /reports/demo/demo_report.html)
REPORTS_DIR = Path("data/out")
if not REPORTS_DIR.exists():
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_DIR, html=True), name="reports")

@app.delete("/api/reports/{submission_id}")
async def delete_report(submission_id: str):
    """
    Delete a report and its associated files.
    """
    # Defensive check against directory traversal
    if ".." in submission_id or "/" in submission_id or "\\" in submission_id:
         raise HTTPException(status_code=400, detail="Invalid submission ID")

    # Find the report directory
    # Structure: data/out/{task}/{student}/{sub_id}/...
    found = False
    
    # Brute force search for simplicity given the varying depth/structure or just use glob
    # We know the ID is unique enough
    # Try to find the folder ending in submission_id
    
    target_dir = None
    
    # Search in data/out
    for path in REPORTS_DIR.glob(f"**/{submission_id}"):
        if path.is_dir():
             target_dir = path
             break
             
    if not target_dir:
        # It might be a flat structure or just a file in some legacy cases, but we standardized on folders
        # Let's try to look for the JSON file to locate it
        for path in REPORTS_DIR.glob(f"**/{submission_id}.json"):
             target_dir = path.parent
             break
             
    if target_dir and target_dir.exists():
         import shutil
         try:
             shutil.rmtree(target_dir)
             found = True
             logger.info(f"Deleted report dir: {target_dir}")
         except Exception as e:
             logger.error(f"Failed to delete {target_dir}: {e}")
             raise HTTPException(status_code=500, detail=f"Failed to delete report files: {e}")
    else:
         # Check if it was just a loose HTML file (unlikely in new structure but possible)
         pass

    # Also try to delete the source upload if possible
    # We don't easily know the exact date folder, but we can search or just ignore it
    # For now, we focus on removing the report from the list
    
    if not found:
         # Try to check if it matches a JOB id (for Pending/Failed jobs that have no directory)
         pass

    # CRITICAL: Also remove from JOBS persistence
    job_found = False
    
    # Check by key (Job ID)
    if submission_id in JOBS:
        del JOBS[submission_id]
        job_found = True
    else:
        # Check by submission_id value (if key is UUID not sub_id)
        # JOBS keys are job_id (UUID), but submission_id is passed here?
        # Actually server.py list_reports returns 'id' as 'submission_id'. 
        # But JOBS keys are UUIDs. 
        # We need to find the job with this submission_id.
        keys_to_delete = []
        for k, v in JOBS.items():
            if v.submission_id == submission_id:
                keys_to_delete.append(k)
        
        for k in keys_to_delete:
            del JOBS[k]
            job_found = True
            
    if job_found:
        save_jobs()
        logger.info(f"Removed job record associated with {submission_id}")

    if job_found:
        save_jobs()
        logger.info(f"Removed job record associated with {submission_id}")

    if not found and not job_found:
         raise HTTPException(status_code=404, detail="Report/Job not found")
         
    return {"status": "success", "message": f"Report {submission_id} deleted"}

class BatchDeleteRequest(BaseModel):
    ids: list[str]

@app.post("/api/reports/batch-delete")
async def batch_delete_reports(request: BatchDeleteRequest):
    """批量删除报告"""
    deleted_count = 0
    errors = []
    
    # Reload JOBS just in case
    global JOBS
    
    ids_to_remove_from_jobs = []

    # Helper to find dir
    def find_dir(sid):
        for path in REPORTS_DIR.glob(f"**/{sid}"):
            if path.is_dir():
                return path
        return None

    for sub_id in request.ids:
        # 1. Delete Directory (Search recursively)
        report_dir = find_dir(sub_id)
        
        if report_dir and report_dir.exists():
            import shutil
            try:
                shutil.rmtree(report_dir)
                deleted_count += 1
            except Exception as e:
                errors.append(f"Failed to delete dir {sub_id}: {e}")
        else:
            # Maybe it doesn't exist on disk (just job record), that's fine
            pass
        
        # 2. Mark for Job Deletion
        # Check by key
        if sub_id in JOBS:
            ids_to_remove_from_jobs.append(sub_id)
        else:
            # Check by submission_id value
            for k, v in JOBS.items():
                if v.submission_id == sub_id:
                    ids_to_remove_from_jobs.append(k)
                    break
    
    # Remove from JOBS
    for job_id in ids_to_remove_from_jobs:
        if job_id in JOBS:
            del JOBS[job_id]
            
    if ids_to_remove_from_jobs:
        save_jobs()
        
    return {
        "status": "success", 
        "deleted_count": deleted_count, 
        "job_removed_count": len(ids_to_remove_from_jobs),
        "errors": errors
    }

@app.get("/api/reports")
async def list_reports():
    """
    List all generated reports in the output directory.
    """
    reports = []
    if not REPORTS_DIR.exists():
        return reports
        
    # Scan for report.html files recursively
    # The new structure is data/out/{task_id}/{student_id}/{submission_id}/{submission_id}.html
    # We look for all .html files that are not index.html (if any)
    for report_file in REPORTS_DIR.glob("**/*.html"):
        # Skip potential system files or base templates
        if report_file.name == "index.html":
            continue
            
        submission_id = report_file.stem # sub_...
        json_path = report_file.parent / f"{submission_id}.json"
        
        # relative path from REPORTS_DIR (data/out)
        try:
            rel_path = report_file.relative_to(REPORTS_DIR)
            url = f"/reports/{rel_path}"
        except Exception:
            continue

        report_data = {
            "id": submission_id,
            "url": url,
            "timestamp": os.path.getmtime(report_file),
            "student_name": submission_id.split("_")[0], # Default fallback
            "score": None
        }
        
        # Try to load metadata from JSON
        if json_path.exists():
            try:
                import json
                with open(json_path, 'r') as f:
                    data = json.load(f)
                    report_data["score"] = data.get("scores", {}).get("overall_100")
                    meta = data.get("meta", {})
                    # Prefer student_id from meta
                    if meta.get("student_id"):
                        report_data["student_name"] = meta["student_id"]
            except Exception:
                pass
                
        reports.append(report_data)
        
    # Sort by timestamp descending
    reports.sort(key=lambda x: x["timestamp"], reverse=True)
    return reports


@app.get("/api/reports/{submission_id}/data")
async def get_report_data(submission_id: str):
    """
    获取报告的完整 JSON 数据，用于报告生成器
    """
    if ".." in submission_id or "/" in submission_id or "\\" in submission_id:
        raise HTTPException(status_code=400, detail="Invalid submission ID")
    
    # 查找 JSON 文件
    json_path = None
    for path in REPORTS_DIR.glob(f"**/{submission_id}.json"):
        json_path = path
        break
    
    if not json_path or not json_path.exists():
        raise HTTPException(status_code=404, detail="Report data not found")
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {e}")


@app.post("/api/upload")
async def upload_audio(
    file: UploadFile = File(...),
    text: str = Form(""),
    mode: str = Form("auto"),
):
    """
    Async Upload: Saves file and queues job. Returns Job ID immediately.
    """
    import shutil
    import time
    from datetime import datetime
    import hashlib
    import uuid
    import json # For serialization in save_jobs
    from src.models import EngineMode
    
    # Generate IDs
    job_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    submission_id = f"web_{timestamp}_{random_hash}"
    
    # Save Upload
    date_str = datetime.now().strftime("%Y%m%d")
    upload_dir = Path("data/uploads") / date_str
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = upload_dir / f"{submission_id}.mp3"
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        logger.info(f"File saved to {file_path}")
        
        # Save Text Sidecar for persistence
        if text:
            txt_path = upload_dir / f"{submission_id}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(text)
                
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Parse metadata
    import re
    fname_stem = Path(file.filename).stem
    parts = fname_stem.split('_', 1)
    
    if len(parts) == 2:
        raw_student = parts[0]
        raw_task = parts[1]
    else:
        raw_student = fname_stem
        raw_task = "upload"
        
    def safe_meta(s):
        # Allow alphanumeric, chinese, dashes, underscores
        return re.sub(r'[^\w\-\u4e00-\u9fff]', '_', s)
        
    student_id = safe_meta(raw_student)
    task_id = safe_meta(raw_task)
    
    logger.info(f"Upload: filename='{file.filename}' -> raw_student='{raw_student}' -> student_id='{student_id}'")
    
    try:
        target_mode = EngineMode(mode.lower())
    except ValueError:
        target_mode = EngineMode.AUTO
        
    # Handling auto mode text clearing is done in the frontend mostly now, 
    # but strictly if we want to ignore passed text for AUTO, we can unless we want to keep it reference.
    # The previous fix in server.py was:
    if target_mode == EngineMode.AUTO:
        # text = ""  <-- Disabling this to allow sidecar saving if needed, 
        # but the pipeline ignores it anyway if mode is FREE_SPEAKING?
        # Actually pipeline checks engine_mode.
        pass

    # Create Job Entry
    job = Job(
        id=job_id,
        status=JobStatus.QUEUED,
        submission_id=submission_id,
        student_id=student_id,
        task_id=task_id,
        filename=file.filename,
        timestamp=time.time(),
        mode=str(target_mode.value)
    )
    JOBS[job_id] = job
    save_jobs() # Save state
    
    # Enqueue
    metadata = {
        "student_id": student_id,
        "task_id": task_id,
        "submission_id": submission_id,
        "engine_mode": target_mode
    }
    
    await JOB_QUEUE.put((job_id, file_path, text, mode, metadata))
    logger.info(f"Job {job_id} queued for {submission_id}")
    
    return {
        "status": "queued",
        "job_id": job_id,
        "submission_id": submission_id,
        "queue_position": JOB_QUEUE.qsize()
    }

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JOBS[job_id]

@app.get("/api/jobs")
async def list_jobs():
    """List all jobs in memory (active or recently completed)"""
    # Fix: sort jobs by timestamp desc
    all_jobs = list(JOBS.values())
    all_jobs.sort(key=lambda x: x.timestamp, reverse=True)
    return all_jobs

@app.post("/api/jobs/{job_id}/rescore")
async def rescore_job(job_id: str):
    """
    Duplicate an existing job/file and re-queue it for scoring.
    """
    import shutil
    import time
    from datetime import datetime
    import hashlib
    import uuid
    from src.models import EngineMode
    
    # 1. Validate Original Job
    # We might need to look up by submission_id if job_id is not in memory (cleaned up)
    # But for now assuming it's in JOBS or we can find it via reports list?
    # Actually list_reports has ID. Let's support both job_id and submission_id lookups
    
    target_job = JOBS.get(job_id)
    if not target_job:
        # Try to find by submission_id
        for k, v in JOBS.items():
            if v.submission_id == job_id:
                target_job = v
                break
    
    original_file_path = None
    original_filename = "unknown.mp3"
    
    if target_job:
        # Known job, try to find its file in data/uploads/...
        # We don't verify if file exists yet, constructed path logic needs to be robust
        # Job doesn't store full path, we need to reconstruct or search?
        # Aah, `worker` gets `file_path`, but `Job` model only has `filename`. 
        # But wait, `upload_audio` stores file in `data/uploads/{date_str}/{submission_id}.mp3`
        # We don't know date_str easily from Job unless we check timestamp or search.
        
        # Strategy: Search for the file in data/uploads
        upload_root = Path("data/uploads")
        for path in upload_root.glob(f"**/{target_job.submission_id}.*"):
            original_file_path = path
            original_filename = target_job.filename
            break
            
    else:
        # Job might be gone (restarted server), but report exists?
        # If passed ID is a submission_id (from report list UI)
        submission_id = job_id
        upload_root = Path("data/uploads")
        # Find file
        for path in upload_root.glob(f"**/{submission_id}.*"):
            original_file_path = path
            original_filename = f"{submission_id}.mp3" # Fallback
            break
            
    if not original_file_path or not original_file_path.exists():
        raise HTTPException(status_code=404, detail="Original audio file not found. Cannot rescore.")

    # 2. Create New File with Suffix
    # Parse original filename to append _new01
    # Check if already has _newXX
    import re
    
    # Logic: 
    # Logic 1: original filename (from user upload) -> modify stem -> new filename
    # Logic 2: submission_id (system id) -> create new system id
    
    # We want the "filename" metadata to reflect the change so the user sees it in the Report Title?
    # Currently report uses `submission_id` for title mostly, or metadata.
    
    old_stem = Path(original_filename).stem
    # 2. Create New File with Suffix
    # Parse original filename to append _vXX
    import re
    
    old_stem = Path(original_filename).stem
    # Match _v(\d+) or _new(\d+) to be safe, but let's standardize on _v
    match = re.search(r'(_v|_new)(\d+)$', old_stem)
    
    version_label = ""
    if match:
        ver = int(match.group(2))
        new_ver = ver + 1
        # Replace existing suffix with new version
        base_stem = old_stem[:match.start()]
        version_label = f"v{new_ver}"
        new_stem = f"{base_stem}_{version_label}"
    else:
        new_ver = 1
        version_label = f"v{new_ver}"
        new_stem = f"{old_stem}_{version_label}"
        
    new_filename = f"{new_stem}{Path(original_filename).suffix}"
    
    # Generate new system IDs
    new_job_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    new_submission_id = f"web_{timestamp}_{random_hash}"
    
    # Copy file
    date_str = datetime.now().strftime("%Y%m%d")
    upload_dir = Path("data/uploads") / date_str
    upload_dir.mkdir(parents=True, exist_ok=True)
    new_file_path = upload_dir / f"{new_submission_id}{original_file_path.suffix}"
    
    try:
        shutil.copy2(original_file_path, new_file_path)
        logger.info(f"Rescore: Copied {original_file_path} to {new_file_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to copy file: {e}")
        
    # 3. Create New Job
    # We want the student_id to be distinct for the UI
    # Re-use metadata logic but force the version into the student_id
    
    parts = new_stem.split('_', 1)
    if len(parts) == 2:
        raw_student = parts[0]
        raw_task = parts[1]
    else:
        raw_student = new_stem
        raw_task = "rescore"
        
    def safe_meta(s):
        return re.sub(r'[^\w\-]', '_', s)
    
    # Logic: if raw_task contains the version, student_id stays same
    # But user wants to see difference in the list.
    # List displays 'student_name' which comes from 'student_id'.
    # So we MUST append version to student_id.
    
    # Check if student_id already ends with _v\d+
    if re.search(r'_v\d+$', base_student_id):
         # Strip it
         base_student_id = re.sub(r'_v\d+$', '', base_student_id)
         
    student_id = f"{base_student_id}_{version_label}"
    task_id = safe_meta(raw_task)
    
    job = Job(
        id=new_job_id,
        status=JobStatus.QUEUED,
        submission_id=new_submission_id,
        student_id=student_id,
        task_id=task_id,
        filename=new_filename,
        timestamp=time.time(),
        mode=target_job.mode if target_job else "auto" # Preserve mode
    )
    
    JOBS[new_job_id] = job
    save_jobs()
    
    metadata = {
        "student_id": student_id,
        "task_id": task_id,
        "submission_id": new_submission_id,
        "engine_mode": EngineMode.AUTO # Force auto or reuse? Reuse is hard if we don't store it. Auto is safe.
    }
    
    await JOB_QUEUE.put((new_job_id, new_file_path, "", "auto", metadata))
    logger.info(f"Rescore job {new_job_id} queued for {new_submission_id} (derived from {job_id})")
    
    return {
        "status": "queued",
        "job_id": new_job_id,
        "submission_id": new_submission_id,
        "new_filename": new_filename
    }

