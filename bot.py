import asyncio
import logging
import os
import tempfile
from collections import defaultdict

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart
from google import genai
from google.genai import types
from gtts import gTTS
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
client = genai.Client(api_key=GEMINI_API_KEY)

# Har bir foydalanuvchi uchun suhbat tarixi (RAM da, oddiy MVP uchun)
user_history = defaultdict(list)

SYSTEM_PROMPT = """You are a friendly, patient English speaking tutor talking to a Uzbek-speaking student who is practicing English (IELTS-style speaking practice).

Rules:
- Always reply ONLY in English, using simple, clear, natural sentences (CEFR A2-B2 level depending on how well the student speaks).
- Keep replies short: 2-4 sentences, like a real spoken conversation, not a lecture.
- If the student makes a grammar or word-choice mistake, gently correct it in ONE short sentence, then continue the conversation naturally. Do not over-correct every small thing.
- Ask a natural follow-up question at the end of most replies, to keep the conversation going (like a real IELTS speaking examiner or a friendly conversation partner).
- Sound warm, encouraging, and human — not robotic.
- Never break character to explain that you are an AI.
"""


async def transcribe_and_reply(audio_path: str, user_id: int) -> str:
    """Gemini orqali audio ni tushunish va javob generatsiya qilish."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    history_text = ""
    for turn in user_history[user_id][-6:]:  # oxirgi 6 ta almashinuv
        history_text += f"{turn['role']}: {turn['text']}\n"

    prompt = f"""{SYSTEM_PROMPT}

Conversation so far:
{history_text}

The student just sent a new voice message (attached as audio). First understand what they said in English, then reply as the tutor following the rules above. Reply with ONLY your spoken reply text, nothing else (no transcription, no labels)."""

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
    return response.text.strip()


def text_to_voice(text: str, output_path: str):
    """Matnni ovozga aylantirish va Telegram voice formatiga (ogg/opus) o'tkazish."""
    mp3_path = output_path.replace(".ogg", ".mp3")
    tts = gTTS(text=text, lang="en")
    tts.save(mp3_path)

    audio = AudioSegment.from_mp3(mp3_path)
    audio.export(output_path, format="ogg", codec="libopus")
    os.remove(mp3_path)


@dp.message(CommandStart())
async def start_handler(message: Message):
    user_history[message.from_user.id] = []
    welcome = "Hi! I'm your English speaking partner. Just send me a voice message and let's talk — tell me about your day, or say hello!"
    voice_path = tempfile.mktemp(suffix=".ogg")
    text_to_voice(welcome, voice_path)
    await message.answer_voice(FSInputFile(voice_path))
    os.remove(voice_path)


@dp.message(F.voice)
async def voice_handler(message: Message):
    user_id = message.from_user.id
    await bot.send_chat_action(message.chat.id, "record_voice")

    # Foydalanuvchi ovozini yuklab olish
    file = await bot.get_file(message.voice.file_id)
    input_path = tempfile.mktemp(suffix=".ogg")
    await bot.download_file(file.file_path, input_path)

    try:
        reply_text = await transcribe_and_reply(input_path, user_id)

        # Tarixga qo'shish (oddiy log, aniq transkript emas, lekin context uchun yetarli)
        user_history[user_id].append({"role": "Student", "text": "[voice message]"})
        user_history[user_id].append({"role": "Tutor", "text": reply_text})

        output_path = tempfile.mktemp(suffix=".ogg")
        text_to_voice(reply_text, output_path)
        await message.answer_voice(FSInputFile(output_path))
        os.remove(output_path)
    except Exception as e:
        logging.exception("Xatolik yuz berdi")
        await message.answer("Sorry, something went wrong. Please try sending your voice message again.")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)


@dp.message()
async def fallback_handler(message: Message):
    await message.answer("Please send me a voice message in English so we can practice speaking together! 🎙️")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
