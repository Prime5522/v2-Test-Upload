import time
import json
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from config import Config
from plugins.script import Translation
from plugins.functions.ran_text import random_char
from plugins.functions.display_progress import humanbytes

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

user_process = {}

@Client.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in user_process:
        task = user_process.pop(user_id)
        task.cancel()
        await message.reply_text("✅ Your ongoing process has been cancelled. Now you can send a new link.")
    else:
        await message.reply_text("❌ You don't have any ongoing process.")

@Client.on_message(filters.private & filters.regex(pattern=".*http.*"))
async def echo(bot, update: Message):
    logger.info(update.from_user)
    url = update.text.strip()
    youtube_dl_username = None
    youtube_dl_password = None
    file_name = None

    if "|" in url:
        url_parts = url.split("|")
        if len(url_parts) == 2:
            url, file_name = url_parts
        elif len(url_parts) == 4:
            url, file_name, youtube_dl_username, youtube_dl_password = url_parts
    else:
        for entity in update.entities or []:
            if entity.type == "text_link":
                url = entity.url
            elif entity.type == "url":
                o, length = entity.offset, entity.length
                url = url[o: o + length]

    if url:
        url = url.strip()
    if file_name:
        file_name = file_name.strip()
    if youtube_dl_username:
        youtube_dl_username = youtube_dl_username.strip()
    if youtube_dl_password:
        youtube_dl_password = youtube_dl_password.strip()

    logger.info(url)

    command_to_exec = ["yt-dlp", "--no-warnings", "--allow-dynamic-mpd", "-j", url]
    if Config.HTTP_PROXY:
        command_to_exec.extend(["--proxy", Config.HTTP_PROXY])
    if youtube_dl_username:
        command_to_exec.extend(["--username", youtube_dl_username])
    if youtube_dl_password:
        command_to_exec.extend(["--password", youtube_dl_password])

    logger.info(command_to_exec)

    chk = await bot.send_message(
        chat_id=update.chat.id,
        text="Processing your request ⌛",
        disable_web_page_preview=True,
        reply_to_message_id=update.id,
    )

    process = await asyncio.create_subprocess_exec(
        *command_to_exec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    user_process[update.from_user.id] = process

    stdout, stderr = await process.communicate()
    user_process.pop(update.from_user.id, None)

    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()

    logger.info(e_response)

    if e_response and "nonnumeric port" not in e_response:
        await chk.delete()
        await asyncio.sleep(3)
        await bot.send_message(
            chat_id=update.chat.id,
            text=Translation.NO_VOID_FORMAT_FOUND.format(e_response),
            reply_to_message_id=update.id,
            disable_web_page_preview=True,
        )
        return

    if not t_response:
        await chk.delete()
        await bot.send_message(
            chat_id=update.chat.id,
            text="❌ No response from server or unsupported link.",
            reply_to_message_id=update.id
        )
        return

    response_json = json.loads(t_response.split("\n")[0])

    randem = random_char(5)
    save_ytdl_json_path = f"{Config.DOWNLOAD_LOCATION}/{update.from_user.id}_{randem}.json"
    with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
        json.dump(response_json, outfile, ensure_ascii=False)

    inline_keyboard = []

    if "formats" in response_json:
        for formats in response_json["formats"]:
            format_id = formats.get("format_id")
            format_string = formats.get("format_note") or formats.get("format", "Unknown")
            if "DASH" in format_string.upper():
                continue
            format_ext = formats.get("ext", "")
            size = formats.get("filesize") or formats.get("filesize_approx") or 0

            cb_string_video = f"video|{format_id}|{format_ext}|{randem}"

            ikeyboard = [
                InlineKeyboardButton(
                    f"🎬 {format_string} {format_ext} {humanbytes(size)}",
                    callback_data=cb_string_video
                )
            ]
            inline_keyboard.append(ikeyboard)

        if response_json.get("duration"):
            for rate in ["64k", "128k", "320k"]:
                cb_string_audio = f"audio|{rate}|mp3|{randem}"
                inline_keyboard.append([
                    InlineKeyboardButton(
                        f"🎼 MP3 ({rate})", callback_data=cb_string_audio
                    )
                ])

        inline_keyboard.append([
            InlineKeyboardButton("⛔ Close", callback_data="close")
        ])

        reply_markup = InlineKeyboardMarkup(inline_keyboard)

        await chk.delete()

        await bot.send_message(
            chat_id=update.chat.id,
            text=Translation.FORMAT_SELECTION,
            reply_markup=reply_markup,
            reply_to_message_id=update.id,
        )

        # Only now update timeout records for free users (if successful)
        if update.from_user.id not in Config.AUTH_USERS:
            Config.ADL_BOT_RQ[str(update.from_user.id)] = time.time()
    else:
        await chk.delete()
        await bot.send_message(
            chat_id=update.chat.id,
            text="❌ Unable to fetch formats.",
            reply_to_message_id=update.id
        )
        
