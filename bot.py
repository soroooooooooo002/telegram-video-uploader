import asyncio
import os
import threading
import time
import urllib.parse
from flask import Flask
import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

# Web server for Render health checks
app = Flask(__name__)

@app.route("/")
def health_check():
    return "Telegram Uploader active!", 200

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# Read credentials and string session from environment variables
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

TEMP_FILE = "temp_video.mp4"

# Use StringSession instead of file-based session
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

def keep_alive():
    while True:
        time.sleep(600)
        if RENDER_EXTERNAL_URL:
            try:
                requests.get(RENDER_EXTERNAL_URL, timeout=10)
            except Exception:
                pass

def download_file_in_chunks(url, target_path):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    safe_url = urllib.parse.quote(url, safe=":/%?=&-")
    with requests.get(safe_url, stream=True, headers=headers, timeout=60) as r:
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

def parse_blocks(file_path):
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    raw_blocks = content.split("================================================================================")
    parsed_items = []
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        data = {}
        for line in block.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip()] = val.strip()
        if "file_url" in data and data["file_url"] and "title" in data:
            parsed_items.append(data)
    return parsed_items

async def main():
    # Connect directly using the session string
    await client.start()
    print("Connected to Telegram using String Session!")

    threading.Thread(target=keep_alive, daemon=True).start()

    items = parse_blocks("data.txt")
    total_items = len(items)
    print(f"Loaded {total_items} items.")

    for index, item in enumerate(items, 1):
        title = item.get("title", "Untitled Video")
        page_url = item.get("page_url", "")
        file_url = item.get("file_url", "")

        caption = f"**{title}**"
        if page_url:
            caption += f"\n\n🔗 [Watch Original Page]({page_url})"

        try:
            print(f"[{index}/{total_items}] Downloading: {title}...")
            download_file_in_chunks(file_url, TEMP_FILE)

            print(f"[{index}/{total_items}] Uploading...")
            await client.send_file(
                CHANNEL_ID,
                file=TEMP_FILE,
                caption=caption,
                parse_mode="md",
                supports_streaming=True,
            )
            print(f"[{index}/{total_items}] Uploaded successfully!")

        except FloodWaitError as e:
            print(f"FloodWait: Sleeping {e.seconds} seconds...")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            print(f"Error on item {index}: {e}")
        finally:
            if os.path.exists(TEMP_FILE):
                os.remove(TEMP_FILE)

        await asyncio.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    with client:
        client.loop.run_until_complete(main())
