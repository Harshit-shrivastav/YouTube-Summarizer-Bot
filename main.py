import os
import re
import asyncio
import requests 
from telethon import TelegramClient, events
from telethon.tl.custom import Button
from pytube import YouTube
import speech_recognition as sr
from pydub import AudioSegment
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import JSONFormatter
from config import Telegram, Ai
from database import db

system_prompt ="""
Do NOT repeat unmodified content.
Do NOT mention anything like "Here is the summary:" or "Here is a summary of the video in 2-3 sentences:" etc.
User will only give you YouTube video subtitles. For summarizing YouTube video subtitles:
- No word limit on summaries.
- Use Telegram markdowns for better formatting: **bold**, *italic*, `monospace`, ~~strike~~, <u>underline</u>, <pre language="c++">code</pre>.
- Try to cover every concept covered in the subtitles.

For song lyrics, poems, recipes, sheet music, or short creative content:
- Do NOT repeat the full content verbatim.
- Provide short snippets, high-level summaries, analysis, or commentary.

Be helpful without directly copying content."""

# Initialize the Telegram client
client = TelegramClient('bot', Telegram.API_ID, Telegram.API_HASH)

# Speech recognizer
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

def fetch_response(user_prompt, system_prompt):
    url = 'https://llm.h-s.site'
    payload = {
        "system": system_prompt,
        "user": user_prompt
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if 'response' in data[0].get('response', {}):
            return data[0]['response']['response']
        else:
            print("Unexpected response format:", data)
            return "Unexpected response format."
    except (requests.RequestException, ValueError) as e:
        print(f"Error: {e}")
        return "Failed to fetch response!"
    except Exception as e:
        print(e)
        return "Failed to fetch response!"
        
async def get_cfai_response(user_prompt, system_prompt, account_id=Ai.CF_ACCOUNT_ID, auth_token=Ai.CF_API_KEY, model_name="@cf/meta/llama-3.1-8b-instruct"):
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]}
    )
    return response.json().get('result', {}).get('response')

async def get_groq_response(user_prompt, system_prompt):
    try:
        client = Groq(api_key=Ai.GROQ_API_KEY)
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                }
            ],
            model="llama3-8b-8192",
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"Error getting Groq response: {e}")
        return "Error getting AI response."

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
                if Ai.GROQ_API_KEY:
                    summary = await get_groq_response(transcript_text, system_prompt)
                elif not Ai.GROQ_API_KEY and Ai.CF_API_KEY and Ai.CF_ACCOUNT_ID:
                    summary = await get_cfai_response(user_prompt=transcript_text, system_prompt=system_prompt)
                elif not Ai.GROQ_API_KEY and not Ai.CF_API_KEY and not Ai.CF_ACCOUNT_ID:
                    summary = fetch_response(transcript_text, system_prompt)
                else:
                    print("Can't Summarize!")

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

                await x.edit('Just a bit...')
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
                            if Ai.GROQ_API_KEY:
                                summary = await get_groq_response(text, system_prompt)
                            elif not Ai.GROQ_API_KEY and Ai.CF_API_KEY and Ai.CF_ACCOUNT_ID:
                                summary = await get_cfai_response(user_prompt=text, system_prompt=system_prompt)
                            else:
                                summary = fetch_response(text, system_prompt)
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
