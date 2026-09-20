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


# ==========================================
# SAFE MOVIEPY IMPORT
# ==========================================

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

    app.run(
        host="0.0.0.0",
        port=port
    )


# ==========================================
# 2. CONFIGURATION
# ==========================================

API_ID = int(
    os.getenv("API_ID", "0")
)

API_HASH = os.getenv(
    "API_HASH",
    ""
)

SESSION_STRING = os.getenv(
    "SESSION_STRING",
    ""
)

CHANNEL_ID = os.getenv(
    "CHANNEL_ID",
    ""
)

# Optional.
# Leave empty when using Vorao.
RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
)

GROUP_LINK = os.getenv(
    "GROUP_LINK",
    "https://t.me/+T_s1eAvQfykzNmM1"
)


if CHANNEL_ID.startswith("-") or CHANNEL_ID.isdigit():
    CHANNEL_ID = int(CHANNEL_ID)


# ==========================================
# TELEGRAM CHANNEL SCAN SETTINGS
# ==========================================

# Number of recent Telegram messages to scan.
#
# 2000 is much faster than scanning the entire
# channel every startup.
#
# Increase this if your channel contains more
# than 2000 recent uploaded files.
CHANNEL_SCAN_LIMIT = int(
    os.getenv(
        "CHANNEL_SCAN_LIMIT",
        "2000"
    )
)


# ==========================================
# TEMP FILES
# ==========================================

TEMP_FILE = "temp_video.mp4"
TEMP_WEBP = "temp_thumb.webp"
TEMP_JPG = "temp_thumb.jpg"


# ==========================================
# PROGRESS FILES
# ==========================================

COMPLETED_FILE = "completed.txt"
FAILED_FILE = "failed.txt"


# ==========================================
# TELEGRAM CLIENT
# ==========================================

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH
)


# ==========================================
# 3. KEEP ALIVE
# ==========================================

def keep_alive():

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


# ==========================================
# 4. DOWNLOAD FILE
# ==========================================

def download_file_in_chunks(
    url,
    target_path
):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140.0.0.0 "
            "Safari/537.36"
        )
    }

    safe_url = urllib.parse.quote(
        url,
        safe=":/%?=&-"
    )

    timeout = (
        20,
        60
    )

    try:

        print(
            "[Download] Connecting to server...",
            flush=True
        )

        with requests.get(
            safe_url,
            stream=True,
            headers=headers,
            timeout=timeout
        ) as r:

            r.raise_for_status()

            print(
                f"[Download] HTTP {r.status_code}",
                flush=True
            )

            total_size = int(
                r.headers.get(
                    "content-length",
                    0
                )
            )

            downloaded = 0

            if total_size:

                print(
                    f"[Download] Size: "
                    f"{total_size / (1024 * 1024):.2f} MB",
                    flush=True
                )

            else:

                print(
                    "[Download] Size: unknown",
                    flush=True
                )

            with open(
                target_path,
                "wb"
            ) as f:

                last_report = time.time()

                for chunk in r.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    f.write(chunk)

                    downloaded += len(chunk)

                    now = time.time()

                    if (
                        now - last_report
                        >= 5
                    ):

                        downloaded_mb = (
                            downloaded
                            / (1024 * 1024)
                        )

                        if total_size:

                            total_mb = (
                                total_size
                                / (1024 * 1024)
                            )

                            percent = (
                                downloaded
                                / total_size
                            ) * 100

                            print(
                                f"[Download] "
                                f"{downloaded_mb:.2f} MB / "
                                f"{total_mb:.2f} MB "
                                f"({percent:.1f}%)",
                                flush=True
                            )

                        else:

                            print(
                                f"[Download] "
                                f"{downloaded_mb:.2f} MB downloaded",
                                flush=True
                            )

                        last_report = now

            print(
                f"[Download] Completed: "
                f"{downloaded / (1024 * 1024):.2f} MB",
                flush=True
            )

    except requests.exceptions.Timeout as e:

        raise RuntimeError(
            f"Download timeout: {e}"
        )

    except requests.exceptions.HTTPError as e:

        status_code = getattr(
            e.response,
            "status_code",
            "unknown"
        )

        raise RuntimeError(
            f"HTTP error {status_code}: {e}"
        )

    except requests.exceptions.RequestException as e:

        raise RuntimeError(
            f"Download request failed: {e}"
        )


# ==========================================
# 5. PARSE DATA.TXT
# ==========================================

def parse_blocks(file_path):

    if not os.path.exists(
        file_path
    ):

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

    if delimiter in content:

        raw_blocks = content.split(
            delimiter
        )

    else:

        raw_blocks = content.split(
            "\n\n"
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

                data[
                    key.strip()
                ] = val.strip()

        if (
            "file_url" in data
            and data["file_url"]
        ):

            parsed_items.append(
                data
            )

    return parsed_items


# ==========================================
# 6. LOAD COMPLETED
# ==========================================

def load_completed():

    completed = set()

    if not os.path.exists(
        COMPLETED_FILE
    ):

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

                    completed.add(
                        title
                    )

    except Exception as e:

        print(
            f"[Completed] "
            f"Could not read file: {e}",
            flush=True
        )

    return completed


# ==========================================
# 7. SAVE COMPLETED
# ==========================================

def save_completed(title):

    try:

        with open(
            COMPLETED_FILE,
            "a",
            encoding="utf-8"
        ) as f:

            f.write(
                title.strip()
                + "\n"
            )

    except Exception as e:

        print(
            f"[Completed] "
            f"Could not save: {e}",
            flush=True
        )


# ==========================================
# 8. SAVE FAILED
# ==========================================

def save_failed(
    index,
    title,
    url,
    error
):

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
            f"[Failed] "
            f"Could not save failed item: {e}",
            flush=True
        )


# ==========================================
# 9. CHECK RECENT TELEGRAM CHANNEL MESSAGES
# ==========================================

async def get_existing_channel_titles():

    print(
        "Checking recent Telegram channel messages...",
        flush=True
    )

    print(
        f"Channel scan limit: "
        f"{CHANNEL_SCAN_LIMIT} messages",
        flush=True
    )

    existing_titles = set()

    scanned = 0

    try:

        # IMPORTANT:
        # Instead of limit=None, only scan recent messages.
        async for message in client.iter_messages(
            CHANNEL_ID,
            limit=CHANNEL_SCAN_LIMIT
        ):

            scanned += 1

            if message.message:

                text = message.message.strip()

                if text:

                    first_line = (
                        text.splitlines()[0].strip()
                    )

                    # Remove Markdown bold
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

            # Progress every 500 messages
            if scanned % 500 == 0:

                print(
                    f"[Channel Scan] "
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
        f"[Channel Scan] Completed. "
        f"Scanned {scanned} messages.",
        flush=True
    )

    print(
        f"[Channel Scan] Found "
        f"{len(existing_titles)} existing titles.",
        flush=True
    )

    return existing_titles


# ==========================================
# 10. TELEGRAM UPLOAD PROGRESS
# ==========================================

def telegram_upload_progress(
    current,
    total
):

    if total <= 0:
        return

    percent = (
        current / total
    ) * 100

    current_mb = (
        current
        / (1024 * 1024)
    )

    total_mb = (
        total
        / (1024 * 1024)
    )

    last_percent = getattr(
        telegram_upload_progress,
        "_last_percent",
        -1
    )

    current_step = int(
        percent // 5
    ) * 5

    if (
        current_step > last_percent
        or percent >= 100
    ):

        telegram_upload_progress._last_percent = (
            current_step
        )

        print(
            f"[Upload] "
            f"{current_mb:.2f} MB / "
            f"{total_mb:.2f} MB "
            f"({percent:.1f}%)",
            flush=True
        )


# ==========================================
# 11. MAIN
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
            "and update Environment Variables.",
            flush=True
        )

        return

    print(
        "Successfully authorized and connected "
        "to Telegram!",
        flush=True
    )

    # ==========================================
    # START KEEP ALIVE
    # ==========================================

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

    total_items = len(
        items
    )

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

    # ==========================================
    # COMBINE COMPLETED SOURCES
    # ==========================================

    already_done = (
        existing_titles |
        completed_titles
    )

    print(
        f"Total known completed/existing titles: "
        f"{len(already_done)}",
        flush=True
    )

    # ==========================================
    # FIND FIRST MISSING ITEM
    # ==========================================

    start_index = (
        total_items + 1
    )

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

    # ==========================================
    # RESUME POSITION
    # ==========================================

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

        title = item.get(
            "title",
            "Untitled Video"
        ).strip()

        # --------------------------------------
        # SKIP ALREADY COMPLETED
        # --------------------------------------

        if title in already_done:

            continue

        # --------------------------------------
        # GET URLS
        # --------------------------------------

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
        # CAPTION
        # ==========================================

        caption = (
            f"**{title}**\n\n"
            f"[Join Group 🔗]"
            f"({GROUP_LINK})"
        )

        # ==========================================
        # DEFAULT VIDEO DATA
        # ==========================================

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

                print(
                    f"[{index}/{total_items}] "
                    f"Reading video metadata...",
                    flush=True
                )

                with VideoFileClip(
                    TEMP_FILE
                ) as clip:

                    duration = int(
                        clip.duration
                    )

                    width = clip.w

                    height = clip.h

                print(
                    f"[{index}/{total_items}] "
                    f"Video metadata: "
                    f"{width}x{height}, "
                    f"{duration}s",
                    flush=True
                )

            except Exception as e:

                print(
                    f"Failed to extract "
                    f"video metadata: {e}",
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

                    print(
                        f"[{index}/{total_items}] "
                        f"Thumbnail ready.",
                        flush=True
                    )

                except Exception as e:

                    print(
                        f"Failed to process "
                        f"image thumbnail: {e}",
                        flush=True
                    )

            # ==========================================
            # UPLOAD TO TELEGRAM
            # ==========================================

            print(
                f"[{index}/{total_items}] "
                f"Uploading to Telegram...",
                flush=True
            )

            # Reset progress
            telegram_upload_progress._last_percent = -1

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

                progress_callback=(
                    telegram_upload_progress
                )
            )

            # ==========================================
            # MARK COMPLETED
            # ==========================================

            save_completed(
                title
            )

            already_done.add(
                title
            )

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

                if os.path.exists(
                    temp
                ):

                    try:

                        os.remove(
                            temp
                        )

                    except Exception as e:

                        print(
                            f"Could not remove "
                            f"{temp}: {e}",
                            flush=True
                        )

        # ==========================================
        # SMALL DELAY
        # ==========================================

        await asyncio.sleep(
            5
        )


# ==========================================
# 12. ENTRY POINT
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

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    asyncio.run(
        main()
    )
