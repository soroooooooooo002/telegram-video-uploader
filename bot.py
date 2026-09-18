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
# 1. FLASK WEB SERVER
# ==========================================

app = Flask(__name__)


@app.route("/")
def health_check():
    return "Telegram Video Uploader is active and running!", 200


def run_web_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# ==========================================
# 2. CONFIGURATION
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

COMPLETED_FILE = "completed.txt"
FAILED_FILE = "failed.txt"


client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================

def keep_alive():
    """Pings Render periodically."""

    while True:

        time.sleep(600)

        if RENDER_EXTERNAL_URL:

            try:

                requests.get(
                    RENDER_EXTERNAL_URL,
                    timeout=10
                )

            except Exception as e:

                print(
                    f"[Keep-Alive] Ping failed: {e}",
                    flush=True
                )


def download_file_in_chunks(url, target_path):
    """Downloads files in chunks."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36"
        )
    }

    safe_url = urllib.parse.quote(
        url,
        safe=":/%?=&-"
    )

    with requests.get(
        safe_url,
        stream=True,
        headers=headers,
        timeout=60
    ) as r:

        r.raise_for_status()

        with open(target_path, "wb") as f:

            for chunk in r.iter_content(
                chunk_size=8192
            ):

                if chunk:
                    f.write(chunk)


def parse_blocks(file_path):
    """Parses data.txt blocks."""

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

                key, val = line.split(
                    ":",
                    1
                )

                data[key.strip()] = val.strip()


        if (
            "file_url" in data
            and data["file_url"]
        ):

            parsed_items.append(data)


    return parsed_items


# ==========================================
# COMPLETED / FAILED FILE HELPERS
# ==========================================

def load_completed():

    completed = set()

    if not os.path.exists(COMPLETED_FILE):
        return completed

    try:

        with open(
            COMPLETED_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            for line in f:

                title = line.strip()

                if title:
                    completed.add(title)

    except Exception as e:

        print(
            f"[Completed] Could not read file: {e}",
            flush=True
        )

    return completed


def save_completed(title):

    try:

        with open(
            COMPLETED_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(title.strip() + "\n")

    except Exception as e:

        print(
            f"[Completed] Could not save: {e}",
            flush=True
        )


def save_failed(index, title, url, error):

    try:

        with open(
            FAILED_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                f"INDEX: {index}\n"
                f"TITLE: {title}\n"
                f"URL: {url}\n"
                f"ERROR: {error}\n"
                f"{'=' * 80}\n"
            )

    except Exception as e:

        print(
            f"[Failed] Could not save failed item: {e}",
            flush=True
        )


# ==========================================
# CHECK EXISTING CHANNEL
# ==========================================

async def get_existing_channel_titles():

    print(
        "Checking existing channel messages...",
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

                    first_line = (
                        text.splitlines()[0].strip()
                    )

                    # Remove Markdown bold.
                    if (
                        first_line.startswith("**")
                        and first_line.endswith("**")
                    ):

                        first_line = first_line[
                            2:-2
                        ].strip()

                    if first_line:

                        existing_titles.add(
                            first_line
                        )


            if scanned % 10000 == 0:

                print(
                    f"Scanned {scanned} messages...",
                    flush=True
                )


    except FloodWaitError as e:

        print(
            f"FloodWait during channel scan. "
            f"Waiting {e.seconds} seconds...",
            flush=True
        )

        await asyncio.sleep(
            e.seconds + 5
        )

        return await get_existing_channel_titles()


    except Exception as e:

        print(
            f"Channel scan failed: {e}",
            flush=True
        )

        return existing_titles


    print(
        f"Resume check completed. "
        f"Scanned {scanned} channel messages.",
        flush=True
    )

    print(
        f"Found {len(existing_titles)} existing titles.",
        flush=True
    )

    return existing_titles


# ==========================================
# 4. MAIN WORKFLOW
# ==========================================

async def main():

    print(
        "Connecting to Telegram...",
        flush=True
    )


    await client.connect()


    if not await client.is_user_authorized():

        print(
            "CRITICAL AUTH ERROR: "
            "SESSION_STRING is invalid or expired!",
            flush=True
        )

        print(
            "Please generate a new SESSION_STRING "
            "and update Render Environment Variables.",
            flush=True
        )

        return


    print(
        "Successfully authorized and connected "
        "to Telegram!",
        flush=True
    )


    # Start keep-alive
    threading.Thread(
        target=keep_alive,
        daemon=True
    ).start()


    # ==========================================
    # LOAD DATA
    # ==========================================

    items = parse_blocks(
        "data.txt"
    )

    total_items = len(items)


    print(
        f"Loaded {total_items} items to upload.",
        flush=True
    )


    if total_items == 0:

        print(
            "No items found in data.txt.",
            flush=True
        )

        return


    # ==========================================
    # LOAD LOCAL COMPLETED LIST
    # ==========================================

    completed_titles = load_completed()


    if completed_titles:

        print(
            f"Loaded {len(completed_titles)} "
            f"completed items from completed.txt.",
            flush=True
        )


    # ==========================================
    # CHECK TELEGRAM CHANNEL
    # ==========================================

    existing_titles = (
        await get_existing_channel_titles()
    )


    # Combine both sources.
    already_done = (
        existing_titles |
        completed_titles
    )


    # ==========================================
    # FIND FIRST MISSING ITEM
    # ==========================================

    start_index = total_items + 1


    for index, item in enumerate(
        items,
        1
    ):

        title = item.get(
            "title",
            "Untitled Video"
        ).strip()


        if title not in already_done:

            start_index = index

            break


    # ==========================================
    # NOTHING LEFT
    # ==========================================

    if start_index > total_items:

        print(
            "==========================================",
            flush=True
        )

        print(
            "ALL ITEMS ARE ALREADY COMPLETED.",
            flush=True
        )

        print(
            "Nothing new to upload.",
            flush=True
        )

        print(
            "==========================================",
            flush=True
        )

        return


    print(
        f"First missing item found: "
        f"{start_index}/{total_items} - "
        f"{items[start_index - 1].get('title', 'Untitled Video')}",
        flush=True
    )


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


        # Skip items already completed.
        title = item.get(
            "title",
            "Untitled Video"
        ).strip()


        if title in already_done:

            continue


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
                flush=True
            )


            download_file_in_chunks(
                file_url,
                TEMP_FILE
            )


            # ==========================================
            # VIDEO METADATA
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
                    flush=True
                )


            # ==========================================
            # THUMBNAIL
            # ==========================================

            if thumb_url:

                try:

                    print(
                        f"[{index}/{total_items}] "
                        f"Downloading Thumbnail...",
                        flush=True
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
                        flush=True
                    )


            # ==========================================
            # UPLOAD
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

                ]

            )


            # ==========================================
            # ONLY MARK COMPLETED AFTER SUCCESS
            # ==========================================

            save_completed(title)

            already_done.add(title)


            print(
                f"[{index}/{total_items}] "
                f"Uploaded successfully!",
                flush=True
            )

            print(
                f"[COMPLETED] {title}",
                flush=True
            )


        # ==========================================
        # FLOOD WAIT
        # ==========================================

        except FloodWaitError as e:

            print(
                f"Rate limited by Telegram. "
                f"Waiting {e.seconds} seconds...",
                flush=True
            )

            await asyncio.sleep(
                e.seconds + 5
            )

            # Do NOT mark as completed.
            # The item will be retried after restart.


        # ==========================================
        # OTHER ERRORS
        # ==========================================

        except Exception as e:

            print(
                f"Error processing item "
                f"{index} ({title}): {e}",
                flush=True
            )


            save_failed(
                index,
                title,
                file_url,
                str(e)
            )


            print(
                f"[FAILED] Saved to {FAILED_FILE}",
                flush=True
            )


        # ==========================================
        # CLEAN TEMP FILES
        # ==========================================

        finally:

            for temp in [
                TEMP_FILE,
                TEMP_WEBP,
                TEMP_JPG
            ]:

                if os.path.exists(temp):

                    try:

                        os.remove(temp)

                    except Exception as e:

                        print(
                            f"Could not remove "
                            f"{temp}: {e}",
                            flush=True
                        )


        await asyncio.sleep(5)


# ==========================================
# 5. ENTRY POINT
# ==========================================

if __name__ == "__main__":

    if not SESSION_STRING:

        print(
            "CRITICAL ERROR: "
            "'SESSION_STRING' environment variable "
            "is missing!",
            flush=True
        )

        exit(1)


    # Start Flask server
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()


    # Start uploader
    asyncio.run(main())
