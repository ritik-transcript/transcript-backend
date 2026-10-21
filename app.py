"""
TranscriptAI Pro — Backend
Link (Instagram / Facebook) ya file upload -> asli transcript (Groq Whisper)

Flow:
  URL  -> yt-dlp se best audio download -> Groq Whisper -> timestamped segments
  File -> seedha Groq Whisper

Koi fake transcript nahi: fail hoga to saaf error code milega.
API key sirf env se aati hai: GROQ_API_KEY (kabhi code me hardcode nahi).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_MODEL = "whisper-large-v3-turbo"
MAX_GROQ_BYTES = 24 * 1024 * 1024  # Groq limit 25MB — thoda safe margin
ALLOWED_URL_HOSTS = ("instagram.com", "facebook.com", "fb.watch", "fb.com")

app = FastAPI(title="TranscriptAI Pro Backend", version="1.0.0")

# Frontend ek hosted static page hai — har origin se allow karo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscribeURLRequest(BaseModel):
    url: str
    language: str = "auto"  # hi | en | auto


# ---------------------------------------------------------------- helpers

def require_groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SERVER_NOT_CONFIGURED",
                "message": "Server par GROQ_API_KEY set nahi hai. "
                           "Pehle Render me GROQ_API_KEY lagao, phir try karo.",
            },
        )
    return key


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status,
                         detail={"code": code, "message": message})


def shrink_audio_if_needed(path: Path) -> Path:
    """File 24MB se badi ho to ffmpeg se chhota mono mp3 banao (16kHz, 32kbps)."""
    if path.stat().st_size <= MAX_GROQ_BYTES:
        return path
    out = path.with_suffix(".small.mp3")
    # -ac 1 mono, -ar 16000 Whisper ke liye kaafi hai, -b:a 32k size kam karega
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", "16000",
         "-b:a", "32k", str(out)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0 or not out.exists():
        raise error(422, "FILE_TOO_LARGE",
                    "File bahut badi hai (25MB se zyada) aur compress nahi ho payi. "
                    "Chhoti file ya sirf audio try karo.")
    if out.stat().st_size > MAX_GROQ_BYTES:
        raise error(422, "FILE_TOO_LARGE",
                    "File compress ke baad bhi 25MB se badi hai. "
                    "Video ko chhota karo ya audio-only file bhejo.")
    return out


def transcribe_with_groq(audio_path: Path, language: str, api_key: str,
                         source_url: str | None = None) -> dict:
    """Ek audio file Groq Whisper ko bhejo, saaf result dict wapas karo."""
    audio_path = shrink_audio_if_needed(audio_path)

    data: dict = {
        "model": GROQ_MODEL,
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
        "temperature": "0",
    }
    if language in ("hi", "en"):
        data["language"] = language

    try:
        with audio_path.open("rb") as fh:
            files = {"file": (audio_path.name, fh, "application/octet-stream")}
            resp = httpx.post(
                GROQ_URL,
                # Browser-style UA: Groq/Cloudflare kabhi-kabhi default python UA ko
                # 403 (error 1010) se block karta hai — ye header usi ka fix hai.
                headers={"Authorization": f"Bearer {api_key}",
                         "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                         "Accept": "application/json"},
                data=data,
                files=files,
                timeout=httpx.Timeout(600.0, connect=30.0),
            )
    except httpx.HTTPError as exc:
        raise error(502, "GROQ_FAILED",
                    f"Groq se connect nahi ho paya: {exc.__class__.__name__}")

    if resp.status_code == 401:
        raise error(502, "GROQ_AUTH_FAILED",
                    "GROQ_API_KEY galat lag rahi hai. Render me sahi key check karo.")
    if resp.status_code == 413:
        raise error(422, "FILE_TOO_LARGE",
                    "File Groq ke 25MB limit se badi hai. Chhoti file try karo.")
    if resp.status_code != 200:
        raise error(502, "GROQ_FAILED",
                    f"Groq transcription fail hua (HTTP {resp.status_code}). "
                    "Thodi der baad dobara try karo.")

    payload = resp.json()
    segments = [
        {
            "start": round(float(s.get("start", 0)), 2),
            "end": round(float(s.get("end", 0)), 2),
            "text": (s.get("text") or "").strip(),
        }
        for s in (payload.get("segments") or [])
        if (s.get("text") or "").strip()
    ]
    duration = payload.get("duration")
    if duration is None and segments:
        duration = segments[-1]["end"]

    return {
        "text": (payload.get("text") or "").strip(),
        "segments": segments,
        "duration": round(float(duration), 2) if duration else None,
        "language": payload.get("language") or (language if language != "auto" else None),
        "source_url": source_url,
    }


def download_audio(url: str, dest_dir: Path) -> Path:
    """yt-dlp se best audio download karo. Fail ho to honest error code do."""
    import yt_dlp  # lazy import — server start hamesha fast rahe

    outtmpl = str(dest_dir / "audio.%(ext)s")
    opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": 80 * 1024 * 1024,  # absurd badi file pehle hi rok do
        "socket_timeout": 30,
        "retries": 2,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:  # yt-dlp DownloadError + network errors
        msg = str(exc).lower()
        login_hints = ("login", "sign in", "401", "403", "private",
                       "cookies", "log in", "not available in your country",
                       "age")
        if any(h in msg for h in login_hints):
            raise error(
                422, "LOGIN_REQUIRED",
                "Ye video private hai ya Instagram/Facebook login maang raha hai — "
                "server bina login ke download nahi kar sakta. "
                "Public reel try karo, ya video download karke File Upload karo.")
        raise error(
            422, "DOWNLOAD_FAILED",
            "Video download nahi ho paya. Link public hai check karo, "
            "ya video download karke File Upload karo.")

    files = [p for p in dest_dir.iterdir() if p.is_file()]
    if not files:
        raise error(422, "DOWNLOAD_FAILED",
                    "Video se audio nahi mila. Link check karke dobara try karo.")
    return max(files, key=lambda p: p.stat().st_size)


def is_supported_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in ALLOWED_URL_HOSTS)


# ---------------------------------------------------------------- routes

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def root():
    return {"ok": True, "service": "TranscriptAI Pro Backend",
            "endpoints": ["/health", "/transcribe-url", "/transcribe-file"]}


@app.post("/transcribe-url")
def transcribe_url(req: TranscribeURLRequest):
    api_key = require_groq_key()

    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")) or not is_supported_url(url):
        raise error(400, "INVALID_URL",
                    "Sirf Instagram ya Facebook ka valid link do "
                    "(instagram.com / facebook.com / fb.watch).")

    language = (req.language or "auto").lower()
    if language not in ("hi", "en", "auto"):
        language = "auto"

    workdir = Path(tempfile.mkdtemp(prefix="transcript_url_"))
    try:
        audio = download_audio(url, workdir)
        return transcribe_with_groq(audio, language, api_key, source_url=url)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/transcribe-file")
async def transcribe_file(file: UploadFile = File(...),
                          language: str = Form("auto")):
    api_key = require_groq_key()

    language = (language or "auto").lower()
    if language not in ("hi", "en", "auto"):
        language = "auto"

    workdir = Path(tempfile.mkdtemp(prefix="transcript_file_"))
    try:
        suffix = Path(file.filename or "upload").suffix or ".bin"
        dest = workdir / f"upload{suffix}"
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
        if dest.stat().st_size == 0:
            raise error(400, "EMPTY_FILE", "File khaali hai. Dusri file try karo.")
        return transcribe_with_groq(dest, language, api_key, source_url=None)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
