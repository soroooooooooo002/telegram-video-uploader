import asyncio
import os
import threading
import time
import urllib.parse
from flask import Flask
from PIL import Image
import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeVideo

# Safe MoviePy import supporting both v1.x and v2.x
try:
    from moviepy.editor import VideoFileClip
except ImportError:
    from moviepy.video.io.VideoFileClip import VideoFileClip

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

if CHANNEL_ID.startswith("-") or CHANNEL_ID.isdigit():
    CHANNEL_ID = int(CHANNEL_ID)

TEMP_FILE = "temp_video.mp4"
TEMP_WEBP = "temp_thumb.webp"
TEMP_JPG = "temp_thumb.jpg"

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def keep_alive():
    """Pings the Render web service periodically to prevent idling."""
    while True:
        time.sleep(600)
        if RENDER_EXTERNAL_URL:
            try:
                requests.get(RENDER_EXTERNAL_URL, timeout=10)
            except Exception as e:
                print(f"[Keep-Alive] Ping failed: {e}", flush=True)


def download_file_in_chunks(url, target_path):
    """Downloads files in chunks to avoid high memory consumption."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    safe_url = urllib.parse.quote(url, safe=":/%?=&-")

    with requests.get(
        safe_url,
        stream=True,
        headers=headers,
        timeout=60
    ) as r:

        r.raise_for_status()

        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def parse_blocks(file_path):
    """Parses text file containing line blocks."""

    if not os.path.exists(file_path):
        print(
            f"Error: Data file '{file_path}' not found!",
            flush=True
        )
        return []

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as f:
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
# AUTOMATIC RESUME FUNCTION
# ==========================================
async def find_resume_index(items):
    """
    Checks the existing channel messages and finds
    the first item from data.txt that is not already
    present in the channel.

    This allows the uploader to resume automatically
    without manually entering COMPLETED_INDEX.
    """

    print(
        "Checking existing channel messages to find "
        "where to resume...",
        flush=True
    )

    existing_titles = set()

    scanned = 0

    try:

        async for message in client.iter_messages(
            CHANNEL_ID,
            limit=None
        ):

            scanned += 1

            if message.message:

                text = message.message.strip()

                if text:

                    # The title is the first line of the caption.
                    first_line = text.splitlines()[0].strip()

                    # Remove Markdown bold formatting.
                    if (
                        first_line.startswith("**")
                        and first_line.endswith("**")
                    ):
                        first_line = first_line[2:-2].strip()

                    if first_line:
                        existing_titles.add(first_line)

            # Progress display for large channels.
            if scanned % 10000 == 0:

                print(
                    f"Resume check: scanned {scanned} messages...",
                    flush=True
                )

    except FloodWaitError as e:

        print(
            f"Telegram requested a wait of {e.seconds} seconds "
            f"during resume check.",
            flush=True
        )

        await asyncio.sleep(e.seconds + 5)

        return await find_resume_index(items)

    except Exception as e:

        print(
            f"Resume check error: {e}",
            flush=True
        )

        print(
            "Starting from index 1 because the existing "
            "channel could not be checked.",
            flush=True
        )

        return 1

    print(
        f"Resume check completed. "
        f"Scanned {scanned} channel messages.",
        flush=True
    )

    print(
        f"Found {len(existing_titles)} existing titles.",
        flush=True
    )

    # Find the first missing item in the same order
    # as data.txt.
    for index, item in enumerate(items, 1):

        title = item.get(
            "title",
            "Untitled Video"
        ).strip()

        if title not in existing_titles:

            print(
                f"First missing item found: "
                f"{index}/{len(items)} - {title}",
                flush=True
            )

            return index

    # Everything already exists.
    print(
        "All items from data.txt already exist "
        "in the channel.",
        flush=True
    )

    return len(items) + 1


# ==========================================
# 4. MAIN WORKFLOW
# ==========================================
async def main():

    print(
        "Connecting to Telegram...",
        flush=True
    )

    # Direct connection without interactive fallback
    await client.connect()

    if not await client.is_user_authorized():

        print(
            "CRITICAL AUTH ERROR: SESSION_STRING is invalid or expired!",
            flush=True,
        )

        print(
            "Please generate a new SESSION_STRING on your local machine "
            "and update Render Environment Variables.",
            flush=True,
        )

        return

    print(
        "Successfully authorized and connected to Telegram!",
        flush=True
    )

    # Start self-ping thread
    threading.Thread(
        target=keep_alive,
        daemon=True
    ).start()

    # Load items from data.txt
    items = parse_blocks("data.txt")

    total_items = len(items)

    print(
        f"Loaded {total_items} items to upload.",
        flush=True
    )

    # ==========================================
    # AUTOMATICALLY FIND WHERE TO RESUME
    # ==========================================

    start_index = await find_resume_index(items)

    if start_index > total_items:

        print(
            "Nothing new to upload.",
            flush=True
        )

        return

    print(
        f"Starting upload from index "
        f"{start_index}/{total_items}",
        flush=True
    )

    # ==========================================
    # UPLOAD LOOP
    # ==========================================

    for index, item in enumerate(
        items,
        1
    ):

        # Skip items that are already present.
        if index < start_index:
            continue

        title = item.get(
            "title",
            "Untitled Video"
        )

        page_url = item.get(
            "page_url",
            ""
        )

        file_url = item.get(
            "file_url",
            ""
        )

        thumb_url = item.get(
            "thumbnail",
            item.get(
                "thumb_url",
                ""
            )
        )

        # ==========================================
        # NEW CAPTION
        # ==========================================

        caption = (
            f"**{title}**\n\n"
            f"[Join Group 🔗]"
            f"(https://t.me/+T_s1eAvQfykzNmM1)"
        )

        thumb_path = None

        duration = 0
        width = 0
        height = 0

        try:

            # ==========================================
            # DOWNLOAD VIDEO
            # ==========================================

            print(
                f"[{index}/{total_items}] "
                f"Downloading Video: {title}...",
                flush=True,
            )

            download_file_in_chunks(
                file_url,
                TEMP_FILE
            )

            # ==========================================
            # EXTRACT VIDEO ATTRIBUTES
            # ==========================================

            try:

                with VideoFileClip(
                    TEMP_FILE
                ) as clip:

                    duration = int(
                        clip.duration
                    )

                    width = clip.w
                    height = clip.h

            except Exception as e:

                print(
                    f"Failed to extract video metadata: {e}",
                    flush=True,
                )

            # ==========================================
            # DOWNLOAD AND CONVERT THUMBNAIL
            # ==========================================

            if thumb_url:

                try:

                    print(
                        f"[{index}/{total_items}] "
                        f"Downloading Thumbnail...",
                        flush=True,
                    )

                    download_file_in_chunks(
                        thumb_url,
                        TEMP_WEBP
                    )

                    with Image.open(
                        TEMP_WEBP
                    ) as img:

                        rgb_img = img.convert(
                            "RGB"
                        )

                        rgb_img.save(
                            TEMP_JPG,
                            "JPEG"
                        )

                    thumb_path = TEMP_JPG

                except Exception as e:

                    print(
                        f"Failed to process image thumbnail: {e}",
                        flush=True,
                    )

            # ==========================================
            # UPLOAD TO TELEGRAM
            # ==========================================

            print(
                f"[{index}/{total_items}] "
                f"Uploading to Telegram...",
                flush=True
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

                        supports_streaming=True

                    )

                ],

            )

            print(
                f"[{index}/{total_items}] "
                f"Uploaded successfully!",
                flush=True
            )

        except FloodWaitError as e:

            print(
                f"Rate limited by Telegram. "
                f"Waiting {e.seconds} seconds...",
                flush=True
            )

            await asyncio.sleep(
                e.seconds + 5
            )

        except Exception as e:

            print(
                f"Error processing item "
                f"{index} ({title}): {e}",
                flush=True
            )

        finally:

            for temp in [
                TEMP_FILE,
                TEMP_WEBP,
                TEMP_JPG
            ]:

                if os.path.exists(temp):

                    os.remove(temp)

        await asyncio.sleep(5)


# ==========================================
# 5. ENTRY POINT
# ==========================================
if __name__ == "__main__":

    if not SESSION_STRING:

        print(
            "CRITICAL ERROR: "
            "'SESSION_STRING' environment variable is missing!",
            flush=True
        )

        exit(1)

    # Start Flask Web Server
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    # Python 3.14+ compatible entry point
    asyncio.run(main())
