import asyncio
import base64
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
# MANUAL RESUME + GITHUB PROGRESS LEDGER
# ==========================================
# Set START_FROM manually to the 1-based item number you want to process.
# The bot does NOT auto-resume from local files or Telegram channel history.
# Every uploaded/skipped item is recorded in GitHub's already_uploaded.txt.

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()  # owner/repository
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_PROGRESS_FILE = "already_uploaded.txt"

# One attempt only. Failed items are recorded as SKIPPED and the bot continues.
MAX_RETRIES = 1
RETRY_DELAY = max(0, int(os.getenv("RETRY_DELAY", "20") or 20))

# This is the exact 1-based item number to start from on every deployment.
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
# 9. GITHUB PROGRESS LEDGER
# ==========================================

def github_headers():
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_progress_url():
    if not GITHUB_REPOSITORY or "/" not in GITHUB_REPOSITORY:
        return None
    owner, repo = GITHUB_REPOSITORY.split("/", 1)
    return (
        f"https://api.github.com/repos/{owner}/{repo}/contents/"
        f"{urllib.parse.quote(GITHUB_PROGRESS_FILE)}"
    )


def save_processed_item(index, status, title, details=""):
    """Append/update one item in the GitHub ledger; local disk is not the source of truth."""
    url = github_progress_url()
    if not GITHUB_TOKEN or not url:
        print(
            "[GitHub] Progress NOT saved: configure GITHUB_TOKEN and "
            "GITHUB_REPOSITORY (owner/repository).",
            flush=True,
        )
        return False

    clean_title = " ".join(str(title).replace("\t", " ").replace("\r", " ").replace("\n", " ").split())
    clean_details = " ".join(str(details).replace("\t", " ").replace("\r", " ").replace("\n", " ").split())
    new_line = f"{int(index)}\t{status}\t{clean_title}"
    if clean_details:
        new_line += f"\t{clean_details}"

    try:
        response = requests.get(
            url,
            headers=github_headers(),
            params={"ref": GITHUB_BRANCH},
            timeout=20,
        )

        sha = None
        lines = []
        if response.status_code == 200:
            payload = response.json()
            sha = payload.get("sha")
            existing = base64.b64decode(payload.get("content", "")).decode("utf-8", errors="replace")
            lines = [line for line in existing.splitlines() if line.strip()]
        elif response.status_code != 404:
            response.raise_for_status()

        prefix = f"{int(index)}\t"
        lines = [line for line in lines if not line.startswith(prefix)]
        lines.append(new_line)
        content = ("\n".join(lines) + "\n").encode("utf-8")

        body = {
            "message": f"Track item {index}: {status}",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            body["sha"] = sha

        saved = requests.put(url, headers=github_headers(), json=body, timeout=20)
        saved.raise_for_status()
        print(f"[GitHub] Saved item {index}: {status}", flush=True)
        return True

    except Exception as e:
        print(f"[GitHub] Could not save item {index} progress: {e}", flush=True)
        return False


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
    # MANUAL RESUME POSITION
    # ==========================================
    # START_FROM is used exactly as configured. The GitHub ledger is for
    # viewing progress only; it does not automatically change this start index.
    start_index = START_FROM

    print(
        f"[Resume] Manual START_FROM={START_FROM}; "
        f"GitHub progress file: {GITHUB_PROGRESS_FILE}",
        flush=True,
    )

    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print(
            "[GitHub] WARNING: GITHUB_TOKEN and GITHUB_REPOSITORY must be set "
            "for progress to be stored in GitHub.",
            flush=True,
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
        f"Starting item: "
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

                # Upload succeeded: record it in GitHub.
                save_processed_item(index, "UPLOADED", title)

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
                    f"Attempt {attempt}/{MAX_RETRIES}; "
                    f"FloodWait encountered.",
                    flush=True
                )

                if attempt < MAX_RETRIES:
                    # Retry the SAME item after Telegram's requested cooldown.
                    await asyncio.sleep(e.seconds + 5)
                    continue

                save_processed_item(index, "SKIPPED", title, str(e))
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

                # Record the skipped item in GitHub and continue.
                save_processed_item(index, "SKIPPED", title, str(e))
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
