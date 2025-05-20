import os
import re
import asyncio
import requests 
import json
import aiohttp 
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from pytube import YouTube
import speech_recognition as sr
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
from config import Telegram, Ai
from database import db
from llm import get_gemini_response 

system_prompt ="""
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

client = TelegramClient('bot', Telegram.API_ID, Telegram.API_HASH)

recognizer = sr.Recognizer()

async def extract_youtube_transcript(youtube_url):
    try:
        video_id_match = re.search(r"(?<=v=)[^&]+|(?<=youtu.be/)[^?|\n]+", youtube_url)
        video_id = video_id_match.group(0) if video_id_match else None
        if video_id is None:
            return "no transcript"
        loop = asyncio.get_event_loop()
        transcript_list = await loop.run_in_executor(None, YouTubeTranscriptApi.list_transcripts, video_id)
        transcript = transcript_list.find_transcript(['en', 'ja', 'ko', 'de', 'fr', 'ru', 'it', 'es', 'pl', 'uk', 'nl', 'zh-TW', 'zh-CN', 'zh-Hant', 'zh-Hans'])
        transcript_text = ' '.join([item['text'] for item in transcript.fetch()])
        return transcript_text
    except Exception as e:
        print(f"Error: {e}")
        return "no transcript"

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    source_button = Button.url("View Source Code", "https://github.com/Harshit-shrivastav/YouTube-Summarizer-Bot")
    await event.reply(
        'Send me a YouTube link, and I will summarize that video for you in text format.',
        buttons=source_button
    )
    if not await db.is_inserted("users", int(event.sender_id)):
        await db.insert("users", int(event.sender_id))

@client.on(events.NewMessage(pattern='/users', from_users=Telegram.AUTH_USER_ID))
async def users(event):
    try:
        users = len(await db.fetch_all("users"))
        await event.reply(f'Total Users: {users}')
    except Exception as e:
        print(e)

@client.on(events.NewMessage(func=lambda e: e.is_private and not e.text.startswith('/'), pattern=r'(?!^/).*'))
async def handle_message(event):
    url = event.message.message
    print(f"Received URL: {url}")

    # Check if the message is a YouTube link
    if 'youtube.com' in url or 'youtu.be' in url:
        x = await event.reply('Reading the video...')
        print("Attempting to download captions from YouTube...")
        try:
            # Try to get the transcript first
            transcript_text = await extract_youtube_transcript(url)
            if transcript_text != "no transcript":
                print("Transcript fetched successfully.")
                await x.edit('Reading Completed, Summarizing it...')
                summary = ""
                if GOOGLE_API_KEY:
                    try:
                        summary = get_gemini_response(Ai.GOOGLE_API_KEY, transcript_text, system_prompt)
                    except Exception as e:
                        print(e)
                if summary:
                        await x.edit(f'{summary}')
                else:
                        await x.edit("Error: Empty or invalid response.")
            else:
                pass
                # No transcript available, fallback to audio transcription
    else:
        print("Invalid YouTube link.")
        await event.reply('Please send a valid YouTube link.')

@client.on(events.NewMessage(pattern='/bcast', from_users=Telegram.AUTH_USER_ID))
async def bcast(event):
    if not event.reply_to_msg_id:
        return await event.reply(
            "Please use `/bcast` as a reply to the message you want to broadcast."
        )
    msg = await event.get_reply_message()
    xx = await event.reply("Broadcasting...")
    error_count = 0
    users = await db.fetch_all("users")
    for user in users:
        try:
            await client.send_message(int(user[0]), msg)
        except Exception:
            error_count += 1
    await xx.edit(f"Broadcasted message with {error_count} errors.")

client.start(bot_token=Telegram.BOT_TOKEN)
client.run_until_disconnected()
