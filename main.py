import os
import uuid
import subprocess
import logging
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

TMP_DIR = "/tmp/audio"
os.makedirs(TMP_DIR, exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/downsample")
async def downsample(file: UploadFile, output_filename: str | None = None):
    job_id = str(uuid.uuid4())
    tmp_in  = os.path.join(TMP_DIR, f"{job_id}_in.mp3")
    tmp_out = os.path.join(TMP_DIR, f"{job_id}_out.mp3")

    # Write uploaded file to disk
    try:
        with open(tmp_in, "wb") as f:
            content = await file.read()
            f.write(content)
        logger.info(f"[{job_id}] Received {len(content) / 1024 / 1024:.1f} MB")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # Run FFmpeg
    cmd = [
        "ffmpeg", "-y",
        "-i", tmp_in,
        "-ac", "1",       # mono
        "-ar", "16000",   # 16 kHz – optimal for Whisper
        "-b:a", "32k",    # 32 kbps
        tmp_out
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0:
            logger.error(f"[{job_id}] FFmpeg error: {result.stderr}")
            raise HTTPException(status_code=500, detail=f"FFmpeg failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="FFmpeg timed out")
    finally:
        if os.path.exists(tmp_in):
            os.remove(tmp_in)

    out_size = os.path.getsize(tmp_out) / 1024 / 1024
    logger.info(f"[{job_id}] Done. Output size: {out_size:.1f} MB")

    if output_filename:
        download_name = output_filename
    elif file.filename:
        base = os.path.splitext(file.filename)[0]
        download_name = f"{base}_downsampled.mp3"
    else:
        download_name = "downsampled.mp3"

    # Return file, clean up after response is sent
    return FileResponse(
        path=tmp_out,
        media_type="audio/mpeg",
        filename=download_name,
        background=BackgroundTask(os.remove, tmp_out)
    )