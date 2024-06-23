import os
import re
import asyncio
from telethon import TelegramClient, events
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
User will only give you youtube video subtitles, For summarizing YouTube video subtitles:
- No word limit on summaries.
- Use Telegram markdowns for better formatting: **bold**, *italic*, `monospace`, ~~strike~~, <u>underline</u>, <pre language="c++">code</pre>.
- Try to cover every concept that are covered in the subtitles.

For song lyrics, poems, recipes, sheet music, or short creative content:
- Do NOT repeat the full content verbatim.
- This restriction applies even for transformations or translations.
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
    await event.reply('Send me a YouTube link, and I will summarize that video for you in text format.')
    if not await db.is_inserted("users", event.sender_id):
        await db.insert("users", event.sender_id)

@client.on(events.NewMessage(pattern='/users', from_users=Telegram.AUTH_USER_ID))
async def users(event):
    try:
        users = len(await db.fetch_all("users"))
        await event.reply(f'Total Users: {users}')
    except Exception as e:
        print(e)

@client.on(events.NewMessage)
async def handle_message(event):
    url = event.message.message
    if event.message.text.startswith('/start'):
        return
    print(f"Received URL: {url}")

    # Check if the message is a YouTube link
    if 'youtube.com' in url or 'youtu.be' in url:
        x = await event.reply('Attempting to download captions from the YouTube video...')
        print("Attempting to download captions from YouTube...")

        try:
            # Try to get the transcript first
            transcript_text = await extract_youtube_transcript(url)
            if transcript_text != "no transcript":
                print("Transcript fetched successfully.")
                await x.edit('Captions found and downloaded. Summarizing the text...')

                summary = await get_groq_response(transcript_text, system_prompt)
                await x.edit(f'{summary}')
            else:
                # No transcript available, fallback to audio transcription
                await x.edit('No captions found. Downloading audio from the YouTube video...')
                print("No captions found. Downloading audio from YouTube...")

                loop = asyncio.get_event_loop()
                yt = await loop.run_in_executor(None, YouTube, url)
                audio_stream = yt.streams.filter(only_audio=True).first()
                output_file = await loop.run_in_executor(None, audio_stream.download, 'audio.mp4')
                print(f"Downloaded audio to {output_file}")

                await x.edit('Converting audio to text...')
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

                            # Summarize the transcribed text
                            await x.edit('Summarizing the text...')
                            summary = await get_groq_response(text, system_prompt)
                            print(f"Summary: {summary}")
                            await x.edit(f'{summary}')
                        except sr.RequestError:
                            print("API unavailable.")
                            await x.edit('API unavailable.')
                        except sr.UnknownValueError:
                            print("Unable to recognize speech.")
                            await x.edit('Unable to recognize speech.')
                except Exception as e:
                    print(f"Error during transcription: {str(e)}")
                    await x.edit(f'Error during transcription: {str(e)}')
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
            "Please use `/bcast` as reply to the message you want to broadcast."
        )
    msg = await event.get_reply_message()
    xx = await event.reply("In progress...")
    users = await db.fetch_all('users')
    done = error = 0
    for user_id in users:
        try:
            await TelegramBot.send_message(
                int(user_id),
                msg.text.format(user=(await TelegramBot.get_entity(int(user_id))).first_name),
                file=msg.media,
                buttons=msg.buttons,
                link_preview=False,
            )
            done += 1
        except Exception as brd_er:
            log.error("Broadcast error:\nChat: %d\nError: %s", int(user_id), brd_er)
            error += 1
    await xx.edit(f"Broadcast completed.\nSuccess: {done}\nFailed: {error}")
    
async def main():
    await client.start(bot_token=Telegram.BOT_TOKEN)
    print("Bot is running...\nHit 🌟 on github repo if you liked my work and please follow on github for more such repos.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
