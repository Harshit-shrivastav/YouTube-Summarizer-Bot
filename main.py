import os
import re
import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytube import YouTube
import speech_recognition as sr
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi
from config import Telegram, Ai
from database import db

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

async def get_llm_response(prompt):
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
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            data = await response.json()
            return data.get('choices', [{}])[0].get('message', {}).get('content', "")

async def extract_youtube_transcript(youtube_url):
    try:
        video_id_match = re.search(r"(?<=v=)[^&]+|(?<=youtu.be/)[^?|\n]+", youtube_url)
        video_id = video_id_match.group(0) if video_id_match else None
        if not video_id:
            return "no transcript"
        loop = asyncio.get_event_loop()
        transcript_list = await loop.run_in_executor(None, YouTubeTranscriptApi.list_transcripts, video_id)
        transcript = transcript_list.find_transcript(['en', 'ja', 'ko', 'de', 'fr', 'ru', 'it', 'es', 'pl', 'uk', 'nl', 'zh-TW', 'zh-CN', 'zh-Hant', 'zh-Hans'])
        transcript_text = ' '.join([item['text'] for item in transcript.fetch()])
        return transcript_text
    except Exception:
        return "no transcript"

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
    url = message.text
    if 'youtube.com' in url or 'youtu.be' in url:
        status_msg = await message.answer('Reading the video...')
        transcript_text = await extract_youtube_transcript(url)
        if transcript_text != "no transcript":
            await status_msg.edit_text('Reading Completed, Summarizing it...')
            summary = await get_llm_response(transcript_text)
            if summary:
                await status_msg.edit_text(summary)
            else:
                await status_msg.edit_text("Error: Empty or invalid response.")
        else:
            await status_msg.edit_text("No transcript available for this video.")
    else:
        await message.answer('Please send a valid YouTube link.')

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
