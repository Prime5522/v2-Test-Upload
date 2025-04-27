import time
import json
import asyncio
import logging

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram import Client, filters
from config import Config
from plugins.script import Translation
from plugins.functions.ran_text import random_char
from plugins.functions.display_progress import humanbytes

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

user_process = {}

# User cancellation process
@Client.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in user_process:
        task = user_process.pop(user_id)
        task.cancel()
        await message.reply_text("✅ Your ongoing process has been cancelled. Now you can send a new link.")
    else:
        await message.reply_text("❌ You don't have any ongoing process.")

# Process URL links
@Client.on_message(filters.private & filters.regex(pattern=".*http.*"))
async def process_link(bot, update):
    logger.info(update.from_user)
    url = update.text
    youtube_dl_username = None
    youtube_dl_password = None
    file_name = None

    # Check if the link is from YouTube or other supported sites
    if "youtu.be" in url or "youtube.com" in url:
        return await update.reply_text(
            "**Choose Download type**",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Audio 🎵", callback_data="ytdl_audio"),
                        InlineKeyboardButton("Video 🎬", callback_data="ytdl_video"),
                    ]
                ]
            ),
            quote=True,
        )

    # Process custom or drive links
    if "|" in url:
        url_parts = url.split("|")
        if len(url_parts) == 2:
            url = url_parts[0]
            file_name = url_parts[1]
        elif len(url_parts) == 4:
            url = url_parts[0]
            file_name = url_parts[1]
            youtube_dl_username = url_parts[2]
            youtube_dl_password = url_parts[3]
        logger.info(url)
        logger.info(file_name)

    if Config.HTTP_PROXY != "":
        command_to_exec = [
            "yt-dlp",
            "--no-warnings",
            "--allow-dynamic-mpd",
            "-j",
            url,
            "--proxy",
            Config.HTTP_PROXY,
        ]
    else:
        command_to_exec = ["yt-dlp", "--no-warnings", "--allow-dynamic-mpd", "-j", url]
    if youtube_dl_username:
        command_to_exec.append("--username")
        command_to_exec.append(youtube_dl_username)
    if youtube_dl_password:
        command_to_exec.append("--password")
        command_to_exec.append(youtube_dl_password)

    # Message to inform user about processing
    chk = await bot.send_message(
        chat_id=update.chat.id,
        text="⌛ Processing your link...",
        disable_web_page_preview=True,
        reply_to_message_id=update.id,
    )

    if update.from_user.id not in Config.AUTH_USERS:
        if str(update.from_user.id) in Config.ADL_BOT_RQ:
            current_time = time.time()
            previous_time = Config.ADL_BOT_RQ[str(update.from_user.id)]
            process_max_timeout = round(Config.PROCESS_MAX_TIMEOUT / 60)
            present_time = round(Config.PROCESS_MAX_TIMEOUT - (current_time - previous_time))
            Config.ADL_BOT_RQ[str(update.from_user.id)] = time.time()
            if round(current_time - previous_time) < Config.PROCESS_MAX_TIMEOUT:
                await bot.edit_message_text(
                    chat_id=update.chat.id,
                    text=Translation.FREE_USER_LIMIT_Q_SZE.format(
                        process_max_timeout, present_time
                    ),
                    disable_web_page_preview=True,
                    message_id=chk.id,
                )
                return

        else:
            Config.ADL_BOT_RQ[str(update.from_user.id)] = time.time()

    # Execute download command
    process = await asyncio.create_subprocess_exec(
        *command_to_exec, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()

    if e_response and "nonnumeric port" not in e_response:
        error_message = e_response.replace(
            """
            please report this issue on https://yt-dl.org/bug . Make sure you are using the latest version;
            """,
            "",
        )
        await chk.delete()

        time.sleep(40.5)
        await bot.send_message(
            chat_id=update.chat.id,
            text=Translation.NO_VOID_FORMAT_FOUND.format(str(error_message)),
            reply_to_message_id=update.id,
            disable_web_page_preview=True,
        )
        return

    if t_response:
        response_json = json.loads(t_response.split("\n")[0])
        randem = random_char(5)
        save_ytdl_json_path = (
            Config.DOWNLOAD_LOCATION
            + "/"
            + str(update.from_user.id)
            + f"{randem}"
            + ".json"
        )
        with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
            json.dump(response_json, outfile, ensure_ascii=False)

        inline_keyboard = []
        duration = response_json.get("duration")
        if "formats" in response_json:
            for formats in response_json["formats"]:
                format_id = formats.get("format_id")
                format_string = formats.get("format_note")
                format_ext = formats.get("ext")
                size = formats.get("filesize", 0) or formats.get("filesize_approx", 0)

                cb_string_video = f"video|{format_id}|{format_ext}|{randem}"
                inline_keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"🎬 {format_string or format_id} {humanbytes(size)}",
                            callback_data=cb_string_video.encode("UTF-8"),
                        )
                    ]
                )

        # Add a close button for the user
        inline_keyboard.append([InlineKeyboardButton("⛔ Close", callback_data="close")])

        reply_markup = InlineKeyboardMarkup(inline_keyboard)
        await chk.delete()

        await bot.send_message(
            chat_id=update.chat.id,
            text=Translation.FORMAT_SELECTION.format("Custom Thumbnail") + "\n" + Translation.SET_CUSTOM_USERNAME_PASSWORD,
            reply_markup=reply_markup,
            reply_to_message_id=update.id,
)
    
