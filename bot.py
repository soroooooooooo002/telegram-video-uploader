import asyncio
import os
import threading
import time
import urllib.parse
from flask import Flask
from moviepy.editor import VideoFileClip
from PIL import Image
import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo

# ==========================================
# 1. FLASK WEB SERVER (For Render Health Checks)
# ==========================================
app = Flask(__name__)


@app.route("/")
def health_check():
    return "Telegram Video Uploader is active and running!", 200


def run_web_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# ==========================================
# 2. CONFIGURATION & ENVIRONMENT VARIABLES
# ==========================================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")

# Convert Channel ID to integer if it is numeric (e.g., -1001234567890)
if CHANNEL_ID.startswith("-") or CHANNEL_ID.isdigit():
    CHANNEL_ID = int(CHANNEL_ID)

TEMP_FILE = "temp_video.mp4"
TEMP_WEBP = "temp_thumb.webp"
TEMP_JPG = "temp_thumb.jpg"

# Initialize Telethon Client with StringSession
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def keep_alive():
    """Pings the Render web service periodically to prevent idling."""
    while True:
        time.sleep(600)  # Ping every 10 minutes
        if RENDER_EXTERNAL_URL:
            try:
                requests.get(RENDER_EXTERNAL_URL, timeout=10)
            except Exception as e:
                print(f"[Keep-Alive] Ping failed: {e}", flush=True)


def download_file_in_chunks(url, target_path):
    """Downloads video files and thumbnails in chunks to preserve memory."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    safe_url = urllib.parse.quote(url, safe=":/%?=&-")
    with requests.get(safe_url, stream=True, headers=headers, timeout=60) as r:
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def parse_blocks(file_path):
    """Parses data.txt file formatted with block structures or blank lines."""
    if not os.path.exists(file_path):
        print(f"Error: Data file '{file_path}' not found!", flush=True)
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    delimiter = (
        "================================================================================"
    )
    raw_blocks = (
        content.split(delimiter)
        if delimiter in content
        else content.split("\n\n")
    )

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
        if "file_url" in data and data["file_url"]:
            parsed_items.append(data)
    return parsed_items


# ==========================================
# 4. MAIN WORKFLOW
# ==========================================
async def main():
    print("Connecting to Telegram via StringSession...", flush=True)
    await client.start()
    print("Successfully connected to Telegram!", flush=True)

    # Start self-ping thread for Render
    threading.Thread(target=keep_alive, daemon=True).start()

    # Load items from data.txt
    items = parse_blocks("data.txt")
    total_items = len(items)
    print(f"Loaded {total_items} items to upload.", flush=True)

    for index, item in enumerate(items, 1):
        title = item.get("title", "Untitled Video")
        page_url = item.get("page_url", "")
        file_url = item.get("file_url", "")
        thumb_url = item.get("thumb_url", "")

        # Format Telegram caption with Markdown
        caption = f"**{title}**"
        if page_url:
            caption += f"\n\n🔗 [Watch Original Page]({page_url})"

        thumb_path = None
        duration = 0
        width = 0
        height = 0

        try:
            # 1. Download Video File
            print(
                f"[{index}/{total_items}] Downloading Video: {title}...",
                flush=True,
            )
            download_file_in_chunks(file_url, TEMP_FILE)

            # 2. Extract Duration and Dimensions for Video Player
            try:
                with VideoFileClip(TEMP_FILE) as clip:
                    duration = int(clip.duration)
                    width = clip.w
                    height = clip.h
            except Exception as e:
                print(
                    f"Failed to extract video duration metadata: {e}",
                    flush=True,
                )

            # 3. Download and Convert Thumbnail (.webp -> .jpg)
            if thumb_url:
                try:
                    print(
                        f"[{index}/{total_items}] Downloading Thumbnail...",
                        flush=True,
                    )
                    download_file_in_chunks(thumb_url, TEMP_WEBP)

                    with Image.open(TEMP_WEBP) as img:
                        rgb_img = img.convert("RGB")
                        rgb_img.save(TEMP_JPG, "JPEG")

                    thumb_path = TEMP_JPG
                except Exception as e:
                    print(
                        f"Failed to process image thumbnail: {e}",
                        flush=True,
                    )

            # 4. Upload Video with Duration and Cover Art
            print(
                f"[{index}/{total_items}] Uploading to Telegram...", flush=True
            )
            await client.send_file(
                CHANNEL_ID,
                file=TEMP_FILE,
                thumb=thumb_path,
                caption=caption,
                parse_mode="md",
                supports_streaming=True,
                attributes=[
                    DocumentAttributeVideo(
                        duration=duration,
                        w=width,
                        h=height,
                        supports_streaming=True,
                    )
                ],
            )
            print(f"[{index}/{total_items}] Uploaded successfully!", flush=True)

        except FloodWaitError as e:
            print(
                f"Rate limited by Telegram. Waiting {e.seconds} seconds...",
                flush=True,
            )
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            print(f"Error processing item {index} ({title}): {e}", flush=True)
        finally:
            # Clean up all local temporary files
            for temp in [TEMP_FILE, TEMP_WEBP, TEMP_JPG]:
                if os.path.exists(temp):
                    os.remove(temp)

        # Rate-limiting delay between uploads
        await asyncio.sleep(5)


# ==========================================
# 5. ENTRY POINT
# ==========================================
if __name__ == "__main__":
    if not SESSION_STRING:
        print(
            "CRITICAL ERROR: 'SESSION_STRING' environment variable is missing!",
            flush=True,
        )
        exit(1)

    # Start Flask Web Server
    threading.Thread(target=run_web_server, daemon=True).start()

    # Run Telethon Event Loop
    with client:
        client.loop.run_until_complete(main())
