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

# Optional on Vorao.
# Leave empty if you are not using Render.
RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
)

# Telegram group link
GROUP_LINK = os.getenv(
    "GROUP_LINK",
    "https://t.me/+T_s1eAvQfykzNmM1"
)

# ==========================================
# CHECKPOINT (no external database)
# ==========================================
# START_FROM is the 1-based item number to begin with on a fresh run.
# checkpoint.txt stores the LAST successfully uploaded item number.
# On restart, resume after the highest confirmed progress from:
#   1. checkpoint.txt
#   2. matching recent Telegram channel posts
#   3. START_FROM - 1 (the initial starting point)
# data.txt is only ever READ, never modified.

PROGRESS_INDEX_FILE = "checkpoint.txt"

# Maximum total attempts per item, including FloodWait retries.
MAX_RETRIES = max(1, int(os.getenv("MAX_RETRIES", "3") or 3))
RETRY_DELAY = max(0, int(os.getenv("RETRY_DELAY", "20") or 20))

# 0 (default): if an item keeps failing, stop and resume from the
#              SAME item on the next start.
# 1          : skip the broken item and continue with the next one.
SKIP_FAILED = os.getenv("SKIP_FAILED", "0") == "1"

# This is the item number to START WITH, not the last completed item.
# Example: START_FROM=890 begins at item 890 if no newer progress exists.
START_FROM = max(1, int(os.getenv("START_FROM", "1") or 1))


if CHANNEL_ID.startswith("-") or CHANNEL_ID.isdigit():
    CHANNEL_ID = int(CHANNEL_ID)


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
    """
    Optional keep-alive.
    Only runs if RENDER_EXTERNAL_URL is configured.
    """

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

def download_file_in_chunks(url, target_path):
    """
    Downloads a file in chunks.

    Includes:
    - HTTP status checking
    - Separate connection/read timeout
    - Download progress
    - File size reporting
    - Better error messages
    """

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

    # Keep URL characters safe.
    safe_url = urllib.parse.quote(
        url,
        safe=":/%?=&-"
    )

    # 20 seconds connection timeout
    # 60 seconds read timeout
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

            # ----------------------------------
            # HTTP STATUS
            # ----------------------------------

            r.raise_for_status()

            print(
                f"[Download] HTTP {r.status_code}",
                flush=True
            )

            # ----------------------------------
            # TOTAL FILE SIZE
            # ----------------------------------

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

            # ----------------------------------
            # OPEN TEMP FILE
            # ----------------------------------

            with open(
                target_path,
                "wb"
            ) as f:

                last_report = time.time()

                # ----------------------------------
                # DOWNLOAD LOOP
                # ----------------------------------

                for chunk in r.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if not chunk:
                        continue

                    f.write(chunk)

                    downloaded += len(chunk)

                    # ----------------------------------
                    # PRINT PROGRESS EVERY 5 SECONDS
                    # ----------------------------------

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

            # ----------------------------------
            # DOWNLOAD COMPLETE
            # ----------------------------------

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
# 9. RESUME CHECKPOINT
# ==========================================

def load_progress_index():
    """Read the local checkpoint (0 if missing)."""

    try:

        with open(
            PROGRESS_INDEX_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return max(
                0,
                int(f.read().strip() or 0)
            )

    except FileNotFoundError:

        return 0

    except Exception as e:

        print(
            f"[Resume] Could not read "
            f"{PROGRESS_INDEX_FILE}: {e}",
            flush=True
        )

        return 0


def save_progress_index(index):
    """Write the local checkpoint. Never crashes the bot."""

    try:

        with open(
            PROGRESS_INDEX_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(str(int(index)))

        print(
            f"[Resume] Checkpoint saved: {index}",
            flush=True
        )

    except Exception as e:

        print(
            f"[Resume] Could not save checkpoint: {e}",
            flush=True
        )


async def find_resume_index_from_channel(items, baseline):
    """
    Looks at the newest channel posts and finds which data.txt
    item was uploaded last (matched by title in the caption).
    Returns that item's index, or 0 if nothing matches.
    This makes resume work even if the host disk is wiped.
    """

    title_map = {}

    for i, it in enumerate(items, 1):

        t = it.get("title", "Untitled Video").strip()

        title_map.setdefault(t, []).append(i)

    try:

        async for msg in client.iter_messages(
            CHANNEL_ID,
            limit=30
        ):

            text = (msg.raw_text or "").strip()

            if not text:
                continue

            first_line = text.split("\n")[0].strip()

            if first_line in title_map:

                candidates = title_map[first_line]

                # Duplicate titles: pick the one nearest to baseline.
                return min(
                    candidates,
                    key=lambda i: abs(i - baseline)
                )

    except Exception as e:

        print(
            f"[Resume] Channel scan failed (ignored): {e}",
            flush=True
        )

    return 0


# ==========================================
# 10. TELEGRAM UPLOAD PROGRESS
# ==========================================

def telegram_upload_progress(
    current,
    total
):
    """
    Telethon upload progress callback.

    current = bytes uploaded
    total   = total bytes
    """

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

    # Store last printed percentage.
    # This prevents thousands of log lines.
    last_percent = getattr(
        telegram_upload_progress,
        "_last_percent",
        -1
    )

    # Print every 5%
    current_step = int(
        percent // 5
    ) * 5

    if (
        current_step > last_percent
        or percent >= 100
    ):

        telegram_upload_progress._last_percent = current_step

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

    # ==========================================
    # CONNECT TELEGRAM
    # ==========================================

    await client.connect()

    if not await client.is_user_authorized():

        print(
            "CRITICAL AUTH ERROR: "
            "SESSION_STRING is invalid or expired!",
            flush=True
        )

        print(
            "Please generate a new SESSION_STRING "
            "and update your Environment Variables.",
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
    # LOAD RESUME CHECKPOINT
    # ==========================================

    local_index = load_progress_index()

    # START_FROM is the first item to upload. Convert it to the previous
    # completed index so START_FROM=890 actually begins with item 890.
    start_from_baseline = START_FROM - 1
    baseline = max(local_index, start_from_baseline)

    channel_index = await find_resume_index_from_channel(
        items,
        baseline
    )

    print(
        f"[Resume] local_last_completed={local_index}, "
        f"START_FROM={START_FROM}, channel_last_match={channel_index}",
        flush=True
    )

    # Persisted/channel progress takes precedence over the initial START_FROM.
    # If item 995 was uploaded, the next run begins at item 996.
    last_completed_index = max(
        local_index,
        start_from_baseline,
        channel_index
    )

    if last_completed_index > total_items:
        last_completed_index = total_items

    start_index = last_completed_index + 1

    print(
        f"[Resume] Checkpoint file: {PROGRESS_INDEX_FILE}",
        flush=True
    )

    print(
        f"[Resume] Last processed item: "
        f"{last_completed_index}/{total_items}",
        flush=True
    )

    if start_index <= total_items:
        print(
            f"[Resume] Starting immediately from item "
            f"{start_index}/{total_items}: "
            f"{items[start_index - 1].get('title', 'Untitled Video')}",
            flush=True
        )

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

        if index < start_index:
            continue

        # --------------------------------------
        # GET TITLE
        # --------------------------------------

        title = item.get(
            "title",
            "Untitled Video"
        ).strip()

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

        attempt = 0

        while True:

            # Fresh state for every attempt.
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

                # Reset upload progress for this file.
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

                    # ==========================================
                    # NEW: TELEGRAM UPLOAD PROGRESS
                    # ==========================================

                    progress_callback=telegram_upload_progress
                )

                # ==========================================
                # MARK COMPLETED
                # ==========================================

                save_completed(
                    title
                )

                # Upload succeeded: permanently mark this index processed.
                save_progress_index(index)

                print(
                    f"[{index}/{total_items}] "
                    f"Uploaded successfully!",
                    flush=True
                )

                print(
                    f"[COMPLETED] {title}",
                    flush=True
                )

                break

            # ==========================================
            # TELEGRAM FLOOD WAIT
            # ==========================================

            except FloodWaitError as e:

                attempt += 1

                print(
                    f"Telegram FloodWait for item {index}. "
                    f"Attempt {attempt}/{MAX_RETRIES}; waiting "
                    f"{e.seconds} seconds...",
                    flush=True
                )

                if attempt < MAX_RETRIES:
                    # Retry the SAME item after Telegram's requested cooldown.
                    await asyncio.sleep(e.seconds + 5)
                    continue

                save_failed(index, title, file_url, str(e))
                save_progress_index(index)
                print(
                    f"[SKIPPED] Item {index} ({title}) reached "
                    f"{MAX_RETRIES} FloodWait attempts. Continuing to the next item.",
                    flush=True
                )
                # Exit this item's retry loop; the outer for-loop advances.
                break

            # ==========================================
            # OTHER ERRORS / SKIPPED ITEMS
            # ==========================================

            except Exception as e:

                attempt += 1

                print(
                    f"Error processing item "
                    f"{index} ({title}) "
                    f"[attempt {attempt}/{MAX_RETRIES}]: {e}",
                    flush=True
                )

                if attempt < MAX_RETRIES:

                    await asyncio.sleep(
                        RETRY_DELAY
                    )

                    continue

                save_failed(
                    index,
                    title,
                    file_url,
                    str(e)
                )

                # Mark this item as processed for resume purposes so a
                # restart cannot get stuck retrying this same broken item.
                # It remains recorded in failed.txt for manual retry later.
                save_progress_index(index)
                print(
                    f"[SKIPPED] Item {index} ({title}) failed "
                    f"{MAX_RETRIES} times. Continuing to the next item.",
                    flush=True
                )
                # Exit this item's retry loop; the outer for-loop advances.
                break

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
        # NO FIXED DELAY
        # ==========================================
        # Start the next item immediately.
        # Telegram FloodWait is handled separately.


# ==========================================
# 12. ENTRY POINT
# ==========================================

if __name__ == "__main__":

    # ==========================================
    # CHECK SESSION
    # ==========================================

    if not SESSION_STRING:

        print(
            "CRITICAL ERROR: "
            "'SESSION_STRING' environment variable "
            "is missing!",
            flush=True
        )

        exit(1)

    # ==========================================
    # START FLASK
    # ==========================================

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    # ==========================================
    # START UPLOADER
    # ==========================================

    asyncio.run(
        main()
    )
