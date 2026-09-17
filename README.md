# Telegram Video Auto Uploader

Automated worker designed for Render Free Tier to parse text block URLs, stream videos, post them to Telegram, and auto-delete temporary files.

## Render Deployment Instructions
1. Upload these files to a GitHub Repository.
2. Go to Render.com -> **New +** -> **Background Worker**.
3. Connect your GitHub Repository.
4. Set Build Command: `pip install -r requirements.txt`
5. Set Start Command: `python bot.py`
6. Add Environment Variables:
   - `API_ID`: Your Telegram API ID
   - `API_HASH`: Your Telegram API Hash
   - `CHANNEL_ID`: `@your_channel_username` (or `-100xxxxxxx`)