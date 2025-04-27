import time
import json
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from config import Config
from plugins.script import Translation
from plugins.functions.ran_text import random_char
from plugins.functions.display_progress import humanbytes

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

user_process = {}
user_caption_choice = {}  # ✅ ইউজারের ক্যাপশন স্টোর করার জন্য
user_waiting_for_caption = {}  # ✅ ইউজার কি এখন ক্যাপশন সেন্ড করবে সেটা ট্র্যাক করার জন্য

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
async def echo(bot, update):
    logger.info(update.from_user)

    url = update.text
    youtube_dl_username = None
    youtube_dl_password = None
    file_name = None

    # ইউজারের লিংক স্টোর করে রাখবো পরবর্তী প্রসেসের জন্য
    user_caption_choice[update.from_user.id] = {"url": url}

    # প্রথমে ক্যাপশন সিলেকশন বাটন দেখাবো
    await update.reply_text(
        "**Choose caption option:**",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Default Caption", callback_data="use_default_caption")],
                [InlineKeyboardButton("📝 Set Custom Caption", callback_data="set_custom_caption")],
            ]
        ),
        quote=True,
    )

@Client.on_callback_query(filters.regex("use_default_caption|set_custom_caption"))
async def caption_choice(bot, query: CallbackQuery):
    user_id = query.from_user.id
    choice = query.data

    if user_id not in user_caption_choice:
        await query.answer("❌ No URL found. Please send the link again.", show_alert=True)
        return

    if choice == "use_default_caption":
        user_caption_choice[user_id]["caption"] = "default"
        await query.message.edit_text("✅ Default caption selected.\n\nProcessing your request... ⏳")
        await process_url(bot, query.message, user_id)

    elif choice == "set_custom_caption":
        user_waiting_for_caption[user_id] = True
        await query.message.edit_text("✍️ Please send your custom caption now.")

@Client.on_message(filters.private & filters.text)
async def get_custom_caption(bot, message: Message):
    user_id = message.from_user.id

    if user_id in user_waiting_for_caption:
        custom_caption = message.text
        user_caption_choice[user_id]["caption"] = custom_caption
        del user_waiting_for_caption[user_id]

        await message.reply_text("✅ Custom caption received.\n\nProcessing your request... ⏳")
        await process_url(bot, message, user_id)

# 🔥 মূল কাজের ফাংশন
async def process_url(bot, message, user_id):
    url = user_caption_choice[user_id]["url"]
    caption_choice = user_caption_choice[user_id]["caption"]

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

    chk = await bot.send_message(
        chat_id=message.chat.id,
        text="Processing your request please wait ✅⌛",
        disable_web_page_preview=True,
        reply_to_message_id=message.id,
    )

    process = await asyncio.create_subprocess_exec(
        *command_to_exec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    user_process[user_id] = process

    stdout, stderr = await process.communicate()

    user_process.pop(user_id, None)

    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()

    logger.info(e_response)

    if e_response and "nonnumeric port" not in e_response:
        await chk.delete()
        await asyncio.sleep(3)
        await bot.send_message(
            chat_id=message.chat.id,
            text=Translation.NO_VOID_FORMAT_FOUND.format(str(e_response)),
            reply_to_message_id=message.id,
            disable_web_page_preview=True,
        )
        return False

    if not t_response:
        await chk.delete()
        await bot.send_message(
            chat_id=message.chat.id,
            text="❌ No valid response received.",
            reply_to_message_id=message.id,
        )
        return

    x_response = t_response.split("\n")[0]
    response_json = json.loads(x_response)

    randem = random_char(5)
    save_ytdl_json_path = (
        Config.DOWNLOAD_LOCATION + "/" + str(user_id) + f"{randem}.json"
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

                cb_string_video = f"video|{format_id}|{format_ext}|{randem}"

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
        cb_string_video = f"video|{format_id}|{format_ext}|{randem}"

        inline_keyboard.append([
            InlineKeyboardButton("🎬 Video", callback_data=cb_string_video)
        ])

        inline_keyboard.append([
            InlineKeyboardButton("📁 Document", callback_data=cb_string_video)
        ])

    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    await chk.delete()

    # 🔥 এখন ক্যাপশন চেক করে পাঠানো হবে
    if caption_choice == "default":
        caption_text = response_json.get("title", "Your File")  # ডিফল্ট ক্যাপশন টাইটেল থেকে
    else:
        caption_text = caption_choice  # ইউজারের দেয়া কাস্টম ক্যাপশন

    await bot.send_message(
        chat_id=message.chat.id,
        text=f"**{caption_text}**\n\n{Translation.FORMAT_SELECTION}",
        reply_markup=reply_markup,
        reply_to_message_id=message.id,
    )

    if user_id not in Config.AUTH_USERS:
        Config.ADL_BOT_RQ[str(user_id)] = time.time()

    # ✅ শেষে ইউজারের ক্যাপশন মেমোরি থেকে রিমুভ করে দিব
    user_caption_choice.pop(user_id, None)
