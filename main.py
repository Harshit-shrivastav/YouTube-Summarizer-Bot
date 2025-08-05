import os
import re
import asyncio
import aiohttp
import logging
from xml.etree.ElementTree import ParseError
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytube import YouTube
import speech_recognition as sr
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from config import Telegram, Ai
from database import db

logging.basicConfig(level=logging.INFO)

system_prompt = """
Do NOT repeat content verbatim unless absolutely necessary.  
Do NOT use phrases like "Here is the summary:" or any similar introductory statements. Avoid filler or redundant wording.  
For summarizing YouTube video subtitles:  
- Summarize concepts **only** from the provided content. Do NOT use any external sources for information.  
- No word limit on summaries.  
- Use **only Telegram markdown** for formatting: **bold**, *italic*, `monospace`, ~~strikethrough~~, and <u>underline</u>, <pre language="c++">code</pre>.  
- Do NOT use any other type of markdown or formatting.  
- Cover **every topic and concept** mentioned in the provided content. Do NOT leave out or skip any part.  
For song lyrics, poems, recipes, sheet music, or short creative content:  
- Do NOT copy the content verbatim unless explicitly requested.  
- Provide short snippets, high-level summaries, analysis, or commentary instead of replicating the content.  
Be strictly helpful, concise, and adhere to the above rules. Summarize thoroughly while staying true to the provided content without adding or omitting any topics. Do not use or mention any formatting except Telegram markdown.
"""

bot = Bot(token=Telegram.BOT_TOKEN)
dp = Dispatcher()
recognizer = sr.Recognizer()

async def get_llm_response(prompt: str) -> str:
    if Ai.API_KEY:
        url = Ai.API_URL
        payload = {
            "model": Ai.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1500,
            "temperature": 0.7
        }
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {Ai.API_KEY}"
        }
    else:
        url = "https://text.pollinations.ai/openai"
        payload = {
            "model": Ai.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "seed": 101,
            "temperature": 0.7
        }
        headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            data = await response.json()
            if 'choices' in data and data['choices']:
                return data['choices'][0]['message']['content']
            elif 'message' in data:
                return data['message']['content']
            return ""

async def extract_youtube_transcript(youtube_url: str) -> str:
    match = re.search(r"(?<=v=)[^&]+|(?<=youtu\.be/)[^?|\n]+", youtube_url)
    if not match:
        return "Invalid YouTube URL."

    video_id = match.group(0)
    preferred_langs = [
        'en', 'ja', 'ko', 'de', 'fr', 'ru', 'it', 'es',
        'pl', 'uk', 'nl', 'zh-TW', 'zh-CN', 'zh-Hant', 'zh-Hans'
    ]

    try:
        loop = asyncio.get_event_loop()
        transcript_list = await loop.run_in_executor(None, YouTubeTranscriptApi.list_transcripts, video_id)

        for lang in preferred_langs:
            try:
                transcript = transcript_list.find_transcript([lang])
                try:
                    return ' '.join([chunk['text'] for chunk in transcript.fetch()])
                except ParseError:
                    return "Captions XML is empty or malformed."
            except NoTranscriptFound:
                continue

        for transcript in transcript_list:
            if not transcript.is_generated:
                try:
                    return ' '.join([chunk['text'] for chunk in transcript.fetch()])
                except ParseError:
                    return "Captions XML is empty or malformed."

        first = transcript_list[0]
        try:
            return ' '.join([chunk['text'] for chunk in first.fetch()])
        except ParseError:
            return "Captions XML is empty or malformed."

    except TranscriptsDisabled:
        return "Transcripts are disabled for this video."
    except NoTranscriptFound as e:
        return f"No transcript found: {e}"
    except Exception as e:
        logging.exception("Unexpected transcript error")
        return f"Unexpected error: {e}"

@dp.message(Command("start"))
async def start_command(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="View Source Code",
        url="https://github.com/Harshit-shrivastav/YouTube-Summarizer-Bot"
    ))
    await message.answer(
        'Send me a YouTube link, and I will summarize that video for you in text format.',
        reply_markup=builder.as_markup()
    )
    if not await db.is_inserted("users", message.from_user.id):
        await db.insert("users", message.from_user.id)

@dp.message(Command("users"))
async def users_command(message: types.Message):
    if message.from_user.id != Telegram.AUTH_USER_ID:
        return
    try:
        users = len(await db.fetch_all("users"))
        await message.answer(f'Total Users: {users}')
    except Exception:
        pass

@dp.message(Command("bcast"))
async def bcast_command(message: types.Message):
    if message.from_user.id != Telegram.AUTH_USER_ID:
        return
    if not message.reply_to_message:
        return await message.answer("Please use `/bcast` as a reply to the message you want to broadcast.")
    msg = message.reply_to_message
    status_msg = await message.answer("Broadcasting...")
    error_count = 0
    users = await db.fetch_all("users")
    for user in users:
        try:
            await bot.copy_message(
                chat_id=int(user),
                from_chat_id=message.chat.id,
                message_id=msg.message_id
            )
        except Exception:
            error_count += 1
    await status_msg.edit_text(f"Broadcasted message with {error_count} errors.")

@dp.message()
async def handle_message(message: types.Message):
    url = message.text.strip()
    if 'youtube.com' in url or 'youtu.be' in url:
        status_msg = await message.answer('Reading the video...')
        transcript_text = await extract_youtube_transcript(url)
        if "captions xml" in transcript_text.lower() or "no transcript" in transcript_text.lower() or "error" in transcript_text.lower():
            await status_msg.edit_text(transcript_text)
        else:
            summary = await get_llm_response(transcript_text)
            if summary.strip():
                await status_msg.edit_text(summary)
            else:
                await status_msg.edit_text("Could not generate summary.")
    else:
        await message.answer('Please send a valid YouTube link.')

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
