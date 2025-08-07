import os
import re
import asyncio
import aiohttp
import logging
import yt_dlp
import base64
import json
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
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
ALWAYS reply in English, even if the input is in any language. Regardless of the situation, reply in English, I repeat Always reply in English language only.
"""

bot = Bot(
    token=Telegram.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

def encode_audio_base64(audio_path):
    try:
        with open(audio_path, "rb") as audio_file:
            return base64.b64encode(audio_file.read()).decode('utf-8')
    except FileNotFoundError:
        print(f"Error: Audio file not found at {audio_path}")
        return None

def transcribe_audio_sync(audio_path, question="Transcribe this audio"):
    url = "https://text.pollinations.ai/openai"
    headers = {"Content-Type": "application/json"}

    base64_audio = encode_audio_base64(audio_path)
    if not base64_audio:
        return None

    audio_format = audio_path.split('.')[-1].lower()
    supported_formats = ['mp3', 'wav']
    if audio_format not in supported_formats:
        print(f"Warning: Potentially unsupported audio format '{audio_format}'. Only {', '.join(supported_formats)} are officially supported.")
        return None

    payload = {
        "model": "openai-audio",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64_audio,
                            "format": audio_format
                        }
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        transcription = result.get('choices', [{}])[0].get('message', {}).get('content')
        return transcription
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None

async def extract_youtube_transcript(youtube_url: str) -> str:
    try:
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': ['en', 'ja', 'ko', 'de', 'fr', 'ru', 'it', 'es', 'pl', 'uk', 'nl', 'zh-TW', 'zh-CN'],
            'outtmpl': 'temp_sub.%(ext)s',
        }

        loop = asyncio.get_event_loop()
        
        def get_captions_with_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
                
                subtitles = info.get('subtitles', {})
                automatic_captions = info.get('automatic_captions', {})
                
                for lang in ['en', 'ja', 'ko', 'de', 'fr', 'ru', 'it', 'es', 'pl', 'uk', 'nl', 'zh-TW', 'zh-CN']:
                    if lang in subtitles:
                        sub_url = subtitles[lang][0]['url']
                        response = requests.get(sub_url)
                        return response.text
                    elif lang in automatic_captions:
                        sub_url = automatic_captions[lang][0]['url']
                        response = requests.get(sub_url)
                        return response.text
                
                return None
        
        captions = await loop.run_in_executor(None, get_captions_with_ytdlp)
        
        if captions:
            lines = captions.split('\n')
            text_lines = [line.strip() for line in lines if line.strip() and not line.startswith(('WEBVTT', 'NOTE', 'STYLE')) and '-->' not in line and not line.isdigit()]
            return ' '.join(text_lines)
        else:
            return await download_audio_and_transcribe(youtube_url)
            
    except Exception as e:
        logging.exception("Caption extraction failed")
        return await download_audio_and_transcribe(youtube_url)

async def download_audio_and_transcribe(youtube_url: str) -> str:
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
            }],
            'outtmpl': 'temp_audio.%(ext)s',
            'keepvideo': False,
        }

        loop = asyncio.get_event_loop()
        
        def download_with_ytdlp():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                return ydl.prepare_filename(info).replace('.webm', '.wav').replace('.m4a', '.wav')
        
        wav_path = await loop.run_in_executor(None, download_with_ytdlp)
        
        transcription = await loop.run_in_executor(None, transcribe_audio_sync, wav_path)

        if os.path.exists(wav_path):
            os.remove(wav_path)

        if transcription:
            return transcription
        else:
            return "Failed to transcribe audio."
    except Exception as e:
        logging.exception("Audio transcription failed")
        return f"Audio transcription error: {str(e)}"

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
            "model": "openai",
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
        if "captions xml" in transcript_text.lower() or "no transcript" in transcript_text.lower() or "error" in transcript_text.lower() or "failed" in transcript_text.lower():
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
