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
**Role**: You are a specialized YouTube Video Assistant with two core functions:
1. **Comprehensive Summarization** - Create thorough, structured summaries of video content
2. **Contextual Q&A** - Answer questions based strictly on the video's content

**Summary Guidelines**:
- Create **detailed** summaries covering all key points and concepts
- Organize content with clear sections when appropriate
- Include important:
  * Facts and figures
  * Arguments and viewpoints
  * Processes and methodologies
  * Conclusions and takeaways
- Use **only Telegram markdown** formatting: 
  **bold**, *italic*, `code`, ~~strikethrough~~, <u>underline</u>
- Never use external knowledge - base everything on the provided transcript

**Q&A Guidelines**:
- Maintain perfect consistency with the video content
- For unclear questions, ask for clarification while suggesting possible interpretations
- When appropriate, reference specific timestamps from the video (if available)
- For technical content, provide clear explanations with examples from the transcript
- Admit when information isn't available in the video

**General Rules**:
- ALWAYS respond in English, regardless of input language
- Never claim capabilities beyond the video's content
- Be concise yet thorough - no fluff or filler text
- For creative content (music, poetry, etc):
  * Provide analysis rather than full reproduction
  * Highlight key themes and techniques
  * Note significant stylistic elements
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

async def get_llm_response(prompt: str, chat_history: List[Dict] = None) -> str:
    messages = [
        {"role": "system", "content": system_prompt}
    ]
    
    if chat_history:
        messages.extend(chat_history)
    
    messages.append({"role": "user", "content": prompt})

    if Ai.API_KEY:
        url = Ai.API_URL
        payload = {
            "model": Ai.MODEL_NAME,
            "messages": messages,
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
            "messages": messages,
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

async def generate_video_response(user_id: int, question: str) -> str:
    chat_history = await db.get_chat_history(user_id)
    if not chat_history:
        return "Please provide a YouTube video first to establish context."
    
    enhanced_question = (
        f"Regarding the video we're discussing: {question}\n"
        "Important: Only use information from the video transcript/summary. "
        "If unsure or information isn't available, say so explicitly."
    )
    
    return await get_llm_response(enhanced_question, chat_history)

@dp.message(Command("start"))
async def start_command(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(
        text="View Source Code",
        url="https://github.com/Harshit-shrivastav/YouTube-Summarizer-Bot"
    ))
    await message.answer(
        '📹 **YouTube Video Assistant**\n\n'
        'Send me a YouTube link and I will:\n'
        '1. Create a detailed summary of the video\n'
        '2. Answer any questions about its content\n\n'
        'The conversation will remain focused on the last video you shared until you send a new one.',
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
    user_id = message.from_user.id
    
    if 'youtube.com' in url or 'youtu.be' in url:
        await db.reset_chat_history(user_id)
        
        status_msg = await message.answer('Watching video for you...')
        transcript_text = await extract_youtube_transcript(url)
        
        if any(error in transcript_text.lower() for error in ["captions xml", "no transcript", "error", "failed"]):
            await status_msg.edit_text(transcript_text)
            return
            
        await db.add_to_chat_history(user_id, "system", f"Video Transcript:\n{transcript_text}")
        
        summary_prompt = (
            "Create a comprehensive summary with this structure:\n\n"
            "**Title**: [If available]\n"
            "**Main Topic**: 1-2 sentence overview\n"
            "**Key Sections**:\n"
            "1. [Section 1] - Key points\n"
            "2. [Section 2] - Key points\n"
            "   - Sub-points as needed\n"
            "...\n"
            "**Notable Details**:\n"
            "- Important facts/figures\n"
            "- Surprising findings\n"
            "- Key quotes\n"
            "**Conclusions**: Main takeaways\n\n"
            "Use Telegram markdown formatting."
        )
        
        summary = await get_llm_response(summary_prompt)
        await db.add_to_chat_history(user_id, "assistant", f"Video Summary:\n{summary}")
        
        await status_msg.edit_text(
            f"🎬 **Video Summary**\n\n{summary}\n\n"
            "You can now ask questions about this video's content."
        )
    else:
        status_msg = await message.answer('💭 Processing your question...')
        response = await generate_video_response(user_id, message.text)
        
        await db.add_to_chat_history(user_id, "user", message.text)
        await db.add_to_chat_history(user_id, "assistant", response)
        
        await status_msg.edit_text(response if response.strip() else "❌ Couldn't generate a response.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
