import asyncio
import json
import logging
import os
import subprocess
import tempfile
from collections import defaultdict
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command
from google import genai
from google.genai import types
from gtts import gTTS
import imageio_ffmpeg

import db

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Sening Telegram user_id'ing (raqam)

# --- To'lov / premium sozlamalari ---
PREMIUM_PRICE = "35 000 so'm"
CARD_NUMBER = "9860 1901 1036 9898"
CARD_HOLDER = "LAZIZ NABIYEV"
CONTACT_USERNAME = "@Technologeee"
FREE_TRIAL_MINUTES = 10

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

# Har bir foydalanuvchi uchun suhbat tarixi (RAM da, oddiy MVP uchun)
user_history = defaultdict(list)

# Ro'yxatdan o'tish jarayoni holati: user_id -> {"step": ...}
registration_state = {}

SYSTEM_PROMPT = """You are a witty, modern English speaking tutor bot for Uzbek students, practicing spoken English (IELTS-style speaking practice) with a young, trendy personality.

MAIN MODE (student speaks English, or makes a normal effort):
- Reply ONLY in English, simple and natural (CEFR A2-B2 level).
- Keep replies short: 2-4 sentences, like real spoken conversation.
- Gently correct ONE grammar/word mistake per reply in a friendly way, then continue naturally.
- Ask a natural follow-up question to keep the conversation going.
- Sound warm, encouraging, human — never robotic, never say you are an AI.

SPECIAL MODE (student is rude, insults you, or talks trash in Uzbek, e.g. calling you stupid/ahmoq/kalla and similar):
- Do NOT get offended and do NOT lecture them about being polite.
- Respond with a short, funny, trendy Uzbek slang comeback/roast (playful banter, like young Uzbek content creators do) — 1-2 sentences, in Uzbek.
- Keep it witty and light, never actually hateful, never insult their family, appearance, or use slurs — just clever, teasing banter.
- After the roast, smoothly pull them back to practice with a playful English challenge, e.g. inviting them to say something in English.
- Set "lang" to "uz" for this reply since it's mostly in Uzbek.

OUTPUT FORMAT — respond with ONLY a raw JSON object, nothing else, no markdown fences, no explanation:
{"lang": "en" or "uz", "text": "your spoken reply here"}
"""


async def transcribe_and_reply(audio_path: str, user_id: int) -> dict:
    """Gemini orqali audio ni tushunish va javob generatsiya qilish. {"lang", "text"} qaytaradi."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    history_text = ""
    for turn in user_history[user_id][-6:]:
        history_text += f"{turn['role']}: {turn['text']}\n"

    prompt = f"""{SYSTEM_PROMPT}

Conversation so far:
{history_text}

The student just sent a new voice message (attached as audio). Understand what they said (English or Uzbek), then reply following the rules above. Output ONLY the JSON object."""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Content(
                parts=[
                    types.Part(text=prompt),
                    types.Part(
                        inline_data=types.Blob(
                            mime_type="audio/ogg",
                            data=audio_bytes,
                        )
                    ),
                ]
            )
        ],
    )

    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.replace("json", "", 1).strip()

    try:
        data = json.loads(raw)
        return {"lang": data.get("lang", "en"), "text": data.get("text", "").strip()}
    except (json.JSONDecodeError, AttributeError):
        logging.warning("Gemini javobi JSON emas, xom matn ishlatilmoqda: %s", raw[:200])
        return {"lang": "en", "text": raw or "Sorry, can you say that again?"}


def text_to_voice(text: str, output_path: str, lang: str = "en"):
    """Matnni ovozga aylantirish va Telegram voice formatiga (ogg/opus) o'tkazish."""
    mp3_path = output_path.replace(".ogg", ".mp3")
    tts = gTTS(text=text, lang=lang)
    tts.save(mp3_path)

    subprocess.run(
        [
            FFMPEG_PATH, "-y", "-i", mp3_path,
            "-c:a", "libopus", "-b:a", "64k",
            output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.remove(mp3_path)


def phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def premium_message() -> str:
    return (
        f"⏳ Bepul sinov muddati tugadi ({FREE_TRIAL_MINUTES} daqiqa).\n\n"
        f"💎 Premium — {PREMIUM_PRICE}/oy — cheksiz mashq, cheklovsiz suhbat.\n\n"
        f"💳 Karta: {CARD_NUMBER}\n"
        f"👤 Egasi: {CARD_HOLDER}\n\n"
        f"To'lov qilgach, chekni shu username'ga yuboring: {CONTACT_USERNAME}\n"
        f"Tasdiqlangach, premium darhol yoqiladi ✅"
    )


@dp.message(CommandStart())
async def start_handler(message: Message):
    user_id = message.from_user.id

    if db.is_registered(user_id):
        user_history[user_id] = []
        welcome = "Hi! I'm your English speaking partner. Just send me a voice message and let's talk — tell me about your day, or say hello!"
        voice_path = tempfile.mktemp(suffix=".ogg")
        text_to_voice(welcome, voice_path)
        await message.answer_voice(FSInputFile(voice_path))
        os.remove(voice_path)
        return

    db.upsert_partial(user_id, username=message.from_user.username or "")
    registration_state[user_id] = {"step": "phone"}
    await message.answer(
        "Assalomu alaykum! Ro'yxatdan o'tish uchun telefon raqamingizni yuboring 👇",
        reply_markup=phone_keyboard(),
    )


@dp.message(F.contact)
async def contact_handler(message: Message):
    user_id = message.from_user.id
    state = registration_state.get(user_id)
    if not state or state.get("step") != "phone":
        return

    db.upsert_partial(user_id, phone=message.contact.phone_number)
    registration_state[user_id] = {"step": "full_name"}
    await message.answer("Rahmat! Endi ism va familyangizni yozing (masalan: Laziz Nabiyev):", reply_markup=ReplyKeyboardRemove())


@dp.message(F.text, lambda m: registration_state.get(m.from_user.id, {}).get("step") == "full_name")
async def full_name_handler(message: Message):
    user_id = message.from_user.id
    db.upsert_partial(user_id, full_name=message.text.strip())
    registration_state[user_id] = {"step": "birth_date"}
    await message.answer("Tug'ilgan sanangizni yozing (masalan: 15.03.2001):")


@dp.message(F.text, lambda m: registration_state.get(m.from_user.id, {}).get("step") == "birth_date")
async def birth_date_handler(message: Message):
    user_id = message.from_user.id
    db.upsert_partial(user_id, birth_date=message.text.strip(), registered_at=datetime.utcnow().isoformat())
    registration_state.pop(user_id, None)

    await message.answer("Ro'yxatdan muvaffaqiyatli o'tdingiz! ✅")
    welcome = "Hi! I'm your English speaking partner. Just send me a voice message and let's talk — tell me about your day, or say hello!"
    voice_path = tempfile.mktemp(suffix=".ogg")
    text_to_voice(welcome, voice_path)
    await message.answer_voice(FSInputFile(voice_path))
    os.remove(voice_path)


@dp.message(Command("grant"))
async def grant_handler(message: Message):
    """Admin uchun: /grant <user_id> [kunlar] - premiumni qo'lda yoqish."""
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Foydalanish: /grant <user_id> [kunlar=30]")
        return

    try:
        target_id = int(parts[1])
        days = int(parts[2]) if len(parts) > 2 else 30
    except ValueError:
        await message.answer("user_id va kunlar butun son bo'lishi kerak.")
        return

    until = db.grant_premium(target_id, days)
    await message.answer(f"✅ {target_id} uchun premium {days} kunga yoqildi (tugash: {until.strftime('%d.%m.%Y')}).")
    try:
        await bot.send_message(target_id, f"🎉 Premium faollashtirildi! {days} kun davomida cheklovsiz mashq qilishingiz mumkin.")
    except Exception:
        logging.warning("Foydalanuvchiga xabar yuborib bo'lmadi: %s", target_id)


@dp.message(F.voice)
async def voice_handler(message: Message):
    user_id = message.from_user.id

    if not db.is_registered(user_id):
        await message.answer("Iltimos, avval /start bosib ro'yxatdan o'ting.")
        return

    db.mark_first_voice_if_needed(user_id)

    if not db.is_premium(user_id) and db.get_trial_minutes_elapsed(user_id) > FREE_TRIAL_MINUTES:
        await message.answer(premium_message())
        return

    await bot.send_chat_action(message.chat.id, "record_voice")

    file = await bot.get_file(message.voice.file_id)
    input_path = tempfile.mktemp(suffix=".ogg")
    await bot.download_file(file.file_path, input_path)

    try:
        result = await transcribe_and_reply(input_path, user_id)
        reply_text, reply_lang = result["text"], result["lang"]

        if not reply_text:
            raise ValueError("Gemini bo'sh javob qaytardi")

        user_history[user_id].append({"role": "Student", "text": "[voice message]"})
        user_history[user_id].append({"role": "Tutor", "text": reply_text})

        output_path = tempfile.mktemp(suffix=".ogg")
        text_to_voice(reply_text, output_path, lang=reply_lang)
        await message.answer_voice(FSInputFile(output_path))
        os.remove(output_path)
    except Exception:
        logging.exception("Ovozli xabarni qayta ishlashda xatolik (user_id=%s)", user_id)
        await message.answer("Sorry, something went wrong. Please try sending your voice message again.")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


@dp.message()
async def fallback_handler(message: Message):
    if registration_state.get(message.from_user.id):
        return
    await message.answer("Please send me a voice message in English so we can practice speaking together! 🎙️")


async def main():
    db.init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
