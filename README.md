# TranscriptAI Pro — Backend

Instagram / Facebook link ya file upload → **asli transcript** (koi fake/demo nahi).

- **Link wala kaam:** server `yt-dlp` se video ka audio download karta hai
- **Transcript wala kaam:** `Groq Whisper` (model `whisper-large-v3-turbo`) — free tier, Hindi me best
- **Fail hoga to saaf error** milega, jhootha transcript kabhi nahi

---

## API

| Method | Path | Kaam |
|---|---|---|
| GET | `/health` | Server zinda hai? → `{"ok": true}` |
| POST | `/transcribe-url` | JSON `{"url": "...", "language": "hi" \| "en" \| "auto"}` |
| POST | `/transcribe-file` | Multipart file upload, field `language` optional |

Success response (dono endpoints):

```json
{
  "text": "pura transcript...",
  "segments": [{"start": 0.0, "end": 4.2, "text": "..."}],
  "duration": 42.0,
  "language": "hi",
  "source_url": "https://www.instagram.com/reel/..."
}
```

Error codes: `INVALID_URL` (400), `LOGIN_REQUIRED` / `DOWNLOAD_FAILED` / `FILE_TOO_LARGE` / `EMPTY_FILE` (422),
`SERVER_NOT_CONFIGURED` (503 — GROQ_API_KEY nahi laga), `GROQ_FAILED` / `GROQ_AUTH_FAILED` (502).

> **Sach baat:** Kuch Instagram/Facebook videos login maangte hain ya private hote hain.
> Unpe server `LOGIN_REQUIRED` error dega — ye Instagram ka rule hai, bug nahi.
> Public reels zyadatar kaam karengi. Fail wali video ko download karke **File Upload** kar do.

---

## Step 1 — Free Groq API Key lo (2 minute, koi card nahi)

1. Kholo: **https://console.groq.com**
2. Apne Google / email se **free account** banao — **koi card nahi lagega**
3. Left side / upar: **API Keys** → **Create API Key**
4. Naam kuch bhi do (jaise `transcript`), key copy karo — `gsk_...` se start hogi
5. Key ko sambhal ke rakho. **Chat / WhatsApp / GitHub pe mat bhejo** — sirf Render me dalegi (Step 3)

Free limits (Oct 2026): ~2,000 requests/day, ~8 hours audio/day — ₹1 wale reels ke liye kaafi hai.

## Step 2 — Code GitHub pe rakho

Render ko code GitHub se milta hai:

1. **https://github.com** pe ek naya **private** repo banao, naam: `transcript-backend`
2. Is folder (`transcript-backend/`) ki saari files us repo me upload karo
   (`app.py`, `requirements.txt`, `Dockerfile`, `render.yaml`, `.env.example`, `README.md`)
3. Dhyaan: `.env` file **mat** upload karna — asli key waha nahi hai, Step 3 me Render me dalegi

## Step 3 — Render pe Free Deploy (5 minute)

1. Kholo: **https://render.com** → free account banao (GitHub se login sabse easy hai)
2. **New +** → **Blueprint** → apna `transcript-backend` repo select karo
   (render.yaml milte hi Render khud Docker service bana dega)
   — ya phir **New + → Web Service → Docker** select karke repo jodo
3. Jab **GROQ_API_KEY** maange, Step 1 wali `gsk_...` key paste karo
   (Blueprint use kiya to: Dashboard → service → **Environment** → `GROQ_API_KEY` ki value dalo)
4. **Deploy** dabao. Pehli build me 3–5 minute lagenge (ffmpeg + packages install hote hain)
5. Deploy ke baad upar tumhara backend URL milega, jaise:
   **`https://transcript-backend.onrender.com`**

Check karo: browser me `https://transcript-backend.onrender.com/health` kholo → `{"ok": true}` aana chahiye.

> **Free plan ki ek baat:** Render free server 15 minute use na ho to so jata hai.
> Pehli request pe jagte hue 30–60 second lag sakte hain — normal hai.

## Step 4 — Muse ko backend URL batao

Bas! Backend URL (jaise `https://transcript-backend.onrender.com`) Muse ko chat me bhej do.
Muse TranscriptAI Pro website ko is backend se jod dega — phir:
**link dalo → ₹1 pay karo → seedha asli transcript milega.**

GROQ_API_KEY Muse ko chat me **mat** bhejna — wo pehle hi Render me lag chuki hogi.

---

## Local test (computer pe)

```bash
pip install -r requirements.txt
GROQ_API_KEY=gsk_... uvicorn app:app --port 8000
curl http://localhost:8000/health
curl -X POST http://localhost:8000/transcribe-url \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://www.instagram.com/reel/XXXX/", "language": "hi"}'
```
