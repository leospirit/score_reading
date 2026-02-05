
import shutil
from pathlib import Path

# Paths
ROOT = Path(".").resolve()
DATA_DIR = ROOT / "data"
REPORTS_DIR = DATA_DIR / "out"
JOBS_FILE = DATA_DIR / "jobs.json"

def cleanup():
    print("🧹 Cleaning up orphaned reports...")
    
    deleted_count = 0
    size_reclaimed_mb = 0.0

    if REPORTS_DIR.exists():
        for item in REPORTS_DIR.iterdir():
            if item.is_dir() or item.suffix == ".json":
                # It's a report or meta file
                try:
                    # Calculate size
                    if item.is_dir():
                        size = sum(f.stat().st_size for f in item.glob('**/*') if f.is_file())
                        shutil.rmtree(item)
                    else:
                        size = item.stat().st_size
                        item.unlink()
                    
                    size_reclaimed_mb += size / (1024 * 1024)
                    deleted_count += 1
                except Exception as e:
                    print(f"Failed to delete {item}: {e}")

    # Also clear jobs.json
    if JOBS_FILE.exists():
        JOBS_FILE.unlink()
        print("🗑️  Cleared job history (jobs.json)")

    print(f"\n✅ Cleanup Complete!")
    print(f"   - Deleted Items: {deleted_count}")
    print(f"   - Space Reclaimed: {size_reclaimed_mb:.2f} MB")

if __name__ == "__main__":
    confirm = input("⚠️  This will delete ALL history reports. Are you sure? (y/n): ")
    if confirm.lower() == "y":
        cleanup()
    else:
        print("Cancelled.")
