import os, json, random, asyncio, subprocess, requests
import edge_tts
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOPICS = ["amazing facts about space", "amazing facts about the human body", "amazing facts about animals", "amazing facts about the ocean", "amazing facts about history", "amazing facts about the brain"]
LANGUAGE = "Hindi"
VOICE = "hi-IN-MadhurNeural"
PRIVACY = "private"
MODELS = ["openrouter/free", "meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free", "mistralai/mistral-small-3.2-24b-instruct:free", "openai/gpt-oss-20b:free"]

def ask_ai(topic):
    prompt = f"Write a 30 second YouTube Shorts script in {LANGUAGE} about: {topic}. About 70 words, interesting facts, no emojis. Reply ONLY with JSON: {{\"title\": \"short catchy title in {LANGUAGE}\", \"script\": \"spoken text\", \"keyword\": \"one or two English words for stock video search\"}}"
    for model in MODELS:
        try:
            r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]}, json={"model": model, "messages": [{"role": "user", "content": prompt}]}, timeout=120)
            text = r.json()["choices"][0]["message"]["content"]
            text = text[text.index("{"): text.rindex("}") + 1]
            return json.loads(text)
        except Exception as e:
            print("model failed:", model, e)
    raise SystemExit("No AI model worked")

async def make_voice(text):
    await edge_tts.Communicate(text, VOICE).save("voice.mp3")

def duration(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(out)

def get_clips(keyword, n=4):
    urls = []
    for q in [keyword, "nature"]:
        r = requests.get("https://pixabay.com/api/videos/", params={"key": os.environ["PIXABAY_API_KEY"], "q": q, "per_page": 10}, timeout=60).json()
        for h in r.get("hits", []):
            v = h["videos"]
            u = (v.get("medium") or v.get("small") or v.get("large"))["url"]
            if u:
                urls.append(u)
        if len(urls) >= n:
            break
    random.shuffle(urls)
    files = []
    for i, u in enumerate(urls[:n]):
        f = f"clip{i}.mp4"
        open(f, "wb").write(requests.get(u, timeout=120).content)
        files.append(f)
    if not files:
        raise SystemExit("No clips found")
    return files

def build_video(clips, total):
    seg = total / len(clips)
    parts = []
    for i, c in enumerate(clips):
        p = f"seg{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-i", c, "-t", str(seg), "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", p], check=True)
        parts.append(p)
    with open("list.txt", "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-i", "voice.mp3", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", "final.mp4"], check=True)

def upload(meta):
    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"], token_uri="https://oauth2.googleapis.com/token", client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"], scopes=["https://www.googleapis.com/auth/youtube.upload"])
    yt = build("youtube", "v3", credentials=creds)
    body = {"snippet": {"title": meta["title"][:90] + " #Shorts", "description": meta["script"] + "\n\n#Shorts", "tags": ["shorts", "facts"], "categoryId": "27"}, "status": {"privacyStatus": PRIVACY, "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload("final.mp4", mimetype="video/mp4", resumable=True)
    res = yt.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print("Uploaded video id:", res["id"])

topic = random.choice(TOPICS)
meta = ask_ai(topic)
print("Title:", meta["title"])
asyncio.run(make_voice(meta["script"]))
clips = get_clips(meta["keyword"])
build_video(clips, duration("voice.mp3"))
open("title.txt", "w").write(meta["title"] + "\n\n" + meta["script"])
