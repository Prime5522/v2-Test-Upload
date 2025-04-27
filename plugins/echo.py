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
user_caption = {}

@Client.on_message(filters.command("cancel"))
async def cancel_command(client, message: Message):
    user_id = message.from_user.id
    if user_id in user_process:
        task = user_process.pop(user_id)
        task.kill()
        await message.reply_text("✅ Your ongoing process has been cancelled. Now you can send a new link.")
    else:
        await message.reply_text("❌ You don't have any ongoing process.")

@Client.on_message(filters.private & filters.regex(pattern=".*http.*"))
async def handle_link(client, message: Message):
    url = message.text

    if "youtu.be" in url:
        return await message.reply_text(
            "**Choose Download type**",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Audio 🎵", callback_data="ytdl_audio"),
                     InlineKeyboardButton("Video 🎬", callback_data="ytdl_video")]
                ]
            ),
            quote=True,
        )

    # Save the url temporarily for the user
    user_process[message.from_user.id] = {"url": url}
    
    await message.reply_text(
        "**Choose Caption Option**",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Default Caption", callback_data="default_caption"),
                 InlineKeyboardButton("Set Caption", callback_data="set_caption")]
            ]
        )
    )

@Client.on_callback_query(filters.regex("default_caption"))
async def default_caption_handler(client, callback_query):
    user_id = callback_query.from_user.id
    data = user_process.get(user_id)

    if not data:
        return await callback_query.message.edit("❌ No URL found. Please send again.")

    url = data["url"]
    await callback_query.message.edit("🔄 Processing your request with Default Caption...")

    await process_url(client, callback_query.message, url)

@Client.on_callback_query(filters.regex("set_caption"))
async def set_caption_handler(client, callback_query):
    user_id = callback_query.from_user.id
    if user_id not in user_process:
        return await callback_query.message.edit("❌ No URL found. Please send again.")

    await callback_query.message.edit("✏️ Please send your custom caption text:")

    user_process[user_id]["awaiting_caption"] = True

@Client.on_message(filters.private)
async def caption_receiver(client, message: Message):
    user_id = message.from_user.id

    if user_id in user_process and user_process[user_id].get("awaiting_caption"):
        caption_text = message.text
        url = user_process[user_id]["url"]

        await message.reply_text("🔄 Processing your request with your Custom Caption...")

        user_caption[user_id] = caption_text
        user_process.pop(user_id, None)  # Done waiting, clean

        await process_url(client, message, url)

async def process_url(client, message, url):
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
        for entity in message.entities or []:
            if entity.type == "text_link":
                url = entity.url
            elif entity.type == "url":
                o, length = entity.offset, entity.length
                url = url[o: o + length]

    if url: url = url.strip()
    if file_name: file_name = file_name.strip()
    if youtube_dl_username: youtube_dl_username = youtube_dl_username.strip()
    if youtube_dl_password: youtube_dl_password = youtube_dl_password.strip()

    command_to_exec = ["yt-dlp", "--no-warnings", "--allow-dynamic-mpd", "-j", url]
    if Config.HTTP_PROXY:
        command_to_exec.extend(["--proxy", Config.HTTP_PROXY])
    if youtube_dl_username:
        command_to_exec.extend(["--username", youtube_dl_username])
    if youtube_dl_password:
        command_to_exec.extend(["--password", youtube_dl_password])

    logger.info(command_to_exec)

    chk = await client.send_message(
        chat_id=message.chat.id,
        text="Processing your request please wait ⌛",
        disable_web_page_preview=True,
        reply_to_message_id=message.id,
    )

    process = await asyncio.create_subprocess_exec(
        *command_to_exec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()

    logger.info(e_response)

    if e_response and "nonnumeric port" not in e_response:
        await chk.delete()
        await asyncio.sleep(3)
        await client.send_message(
            chat_id=message.chat.id,
            text=Translation.NO_VOID_FORMAT_FOUND.format(str(e_response)),
            reply_to_message_id=message.id,
            disable_web_page_preview=True,
        )
        return False

    if not t_response:
        await chk.delete()
        await client.send_message(
            chat_id=message.chat.id,
            text="❌ No valid response received.",
            reply_to_message_id=message.id,
        )
        return

    x_response = t_response.split("\n")[0]
    response_json = json.loads(x_response)

    randem = random_char(5)
    save_ytdl_json_path = (
        Config.DOWNLOAD_LOCATION + "/" + str(message.from_user.id) + f"{randem}.json"
    )

    with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
        json.dump(response_json, outfile, ensure_ascii=False)

    inline_keyboard = []
    duration = response_json.get("duration")

    if "formats" in response_json:
        for formats in response_json["formats"]:
            format_id = formats.get("format_id")
            format_string = formats.get("format_note") or formats.get("format")
            if format_string and "DASH" not in format_string.upper():
                format_ext = formats.get("ext", "")
                size = formats.get("filesize") or formats.get("filesize_approx") or 0

                cb_string_video = f"video |{format_id}|{format_ext}|{randem}"

                ikeyboard = [
                    InlineKeyboardButton(
                        f"🎬 {format_string} {format_ext} {humanbytes(size)}",
                        callback_data=cb_string_video
                    )
                ]
                inline_keyboard.append(ikeyboard)

        if duration:
            for rate in ["64k", "128k", "320k"]:
                cb_string_audio = f"audio|{rate}|mp3|{randem}"
                inline_keyboard.append([
                    InlineKeyboardButton(f"🎼 MP3 ({rate})", callback_data=cb_string_audio)
                ])

        inline_keyboard.append([
            InlineKeyboardButton("⛔ Close", callback_data="close")
        ])

    else:
        format_id = response_json.get("format_id")
        format_ext = response_json.get("ext")
        cb_string_video = f"video |{format_id}|{format_ext}|{randem}"

        inline_keyboard.append([
            InlineKeyboardButton("🎬 Video", callback_data=cb_string_video)
        ])

        inline_keyboard.append([
            InlineKeyboardButton("📁 Document", callback_data=cb_string_video)
        ])

    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    await chk.delete()

    caption_text = user_caption.get(message.from_user.id)
    if caption_text:
        caption = caption_text
    else:
        caption = Translation.FORMAT_SELECTION.format(response_json.get("thumbnail", "")) + "\n" + Translation.SET_CUSTOM_USERNAME_PASSWORD

    await client.send_message(
        chat_id=message.chat.id,
        text=caption,
        reply_markup=reply_markup,
        reply_to_message_id=message.id,
        disable_web_page_preview=True,
    )

    if message.from_user.id not in Config.AUTH_USERS:
        Config.ADL_BOT_RQ[str(message.from_user.id)] = time.time()
