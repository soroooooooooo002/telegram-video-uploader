import asyncio
import os
import urllib.parse
import requests
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# Read configuration from Render Environment Variables
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

TEMP_FILE = "temp_video.mp4"

client = TelegramClient("render_session", API_ID, API_HASH)


def download_file_in_chunks(url, target_path):
    """Streams video directly to disk in 8KB chunks to respect 512MB RAM limits."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    # Encode spaces in URLs if present
    safe_url = urllib.parse.quote(url, safe=":/%?=&-")

    with requests.get(safe_url, stream=True, headers=headers, timeout=60) as r:
        r.raise_for_status()
        with open(target_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)


def parse_blocks(file_path):
    """Parses text file blocks separated by equal sign dividers."""
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
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
    await client.start()
    print("Connected to Telegram successfully!")

    items = parse_blocks("data.txt")
    total_items = len(items)
    print(f"Loaded {total_items} videos to process.")

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

            print(f"[{index}/{total_items}] Uploading to Telegram...")
            await client.send_file(
                CHANNEL_ID,
                file=TEMP_FILE,
                caption=caption,
                parse_mode="md",
                supports_streaming=True,
            )
            print(f"[{index}/{total_items}] Uploaded successfully!")

        except FloodWaitError as e:
            print(f"Telegram Rate Limit: Waiting {e.seconds} seconds...")
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            print(f"Error on video {index} ({title}): {e}")

        finally:
            # Delete temporary download immediately to free disk space
            if os.path.exists(TEMP_FILE):
                os.remove(TEMP_FILE)
                print(f"[{index}/{total_items}] Temp file cleaned up.")

        # Rate limit delay (5 seconds between posts)
        await asyncio.sleep(5)


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())