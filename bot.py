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

        # ==========================================
        # TELEGRAM FLOOD WAIT
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

            # Do NOT mark completed.

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
