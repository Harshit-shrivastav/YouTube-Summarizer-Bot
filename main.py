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
from llm import get_duckai_response, get_arliai_response

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
                try:
                    summary = get_duckai_response(transcript_text, system_prompt)
                except Exception as e:
                    print(e)
                    if Ai.ARLIAI_API_KEY:
                        summary = await fetch_response(Ai.ARLIAI_API_KEY, transcript_text, system_prompt)
                    else:
                        print("Can't Summarize, ARLIAI_API_KEY not found!")
                if summary:
                        await x.edit(f'{summary}')
                else:
                        await x.edit("Error: Empty or invalid response.")
            else:
                # No transcript available, fallback to audio transcription
                await x.edit("Failed to read Video, Trying to listen the video's audio...")
                print("No captions found. Downloading audio from YouTube...")
                loop = asyncio.get_event_loop()
                yt = await loop.run_in_executor(None, YouTube, url)
                audio_stream = yt.streams.filter(only_audio=True).first()
                output_file = await loop.run_in_executor(None, audio_stream.download, 'audio.mp4')
                print(f"Downloaded audio to {output_file}")

                await x.edit('Just a moment...')
                print("Converting audio to text...")

                # Convert audio to WAV format
                try:
                    audio = AudioSegment.from_file(output_file)
                    wav_file = "audio.wav"
                    audio.export(wav_file, format="wav")
                    print(f"Converted audio to {wav_file}")

                    # Convert audio to text
                    with sr.AudioFile(wav_file) as source:
                        recognizer.adjust_for_ambient_noise(source)
                        audio_data = recognizer.record(source)
                        try:
                            text = recognizer.recognize_google(audio_data)
                            print(f"Transcribed text: {text}")
                            
                            await x.edit('Summarizing it...')
                            summary = ""
                            try:
                                summary = get_duckai_response(transcript_text, system_prompt)
                            except Exception as e:
                                print(e)
                                if Ai.ARLIAI_API_KEY:
                                    summary = await fetch_response(Ai.ARLIAI_API_KEY, transcript_text, system_prompt)
                                else:
                                    print("Can't Summarize, ARLIAI_API_KEY not found!")
                            if summary:
                                await x.edit(f'{summary}')
                            else:
                                await x.edit("Error: Empty or invalid response.")
                        except sr.RequestError:
                            print("API unavailable.")
                            await x.edit('API unavailable.')
                        except sr.UnknownValueError:
                            print("Unable to recognize speech.")
                            await x.edit('Unable to recognize speech.')
                except Exception as e:
                    print(f"Error during transcription: {str(e)}")
                    await x.edit(f'Error while listening to audio: {str(e)}')
                finally:
                    # Clean up files
                    if os.path.exists(output_file):
                        os.remove(output_file)
                        print(f"Deleted file: {output_file}")
                    if os.path.exists(wav_file):
                        os.remove(wav_file)
                        print(f"Deleted file: {wav_file}")
        except Exception as e:
            print(f"Error: {str(e)}")
            await x.edit(f'Error: {str(e)}')
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
