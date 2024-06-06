import os
import asyncio
from telethon import TelegramClient, events
from pytube import YouTube
import speech_recognition as sr
from groq import Groq

# Replace these with your own values
api_id = '4680197'
api_hash = '495b0228624028d635bd748b22985f67'
bot_token = '6086267913:AAHLavNglgsuUcsMain9k6bVIQpxpkLmDKk'
GROQ_API_KEY = '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'
system_prompt = "You are a very talented and creative Summarizer, Summarize this article for me."

# Initialize the Telegram client
client = TelegramClient('bot', api_id, api_hash)

# Speech recognizer
recognizer = sr.Recognizer()

async def get_groq_response(user_prompt, system_prompt):
    try:
        client = Groq(api_key=GROQ_API_KEY)
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
        return "Error getting Groq response"

@client.on(events.NewMessage(pattern='/start'))
async def start(event):
    await event.reply('Send me a YouTube link, and I will convert its audio to text.')

@client.on(events.NewMessage)
async def handle_message(event):
    url = event.message.message
    print(f"Received URL: {url}")

    # Check if the message is a YouTube link
    if 'youtube.com' in url or 'youtu.be' in url:
        await event.reply('Attempting to download captions from the YouTube video...')
        print("Attempting to download captions from YouTube...")

        try:
            yt = YouTube(url)
            captions = yt.captions
            caption = captions.get_by_language_code('en')

            if caption:
                # Captions are available, use them
                caption_srt = caption.generate_srt_captions()
                print("Captions downloaded successfully.")
                await event.reply('Captions found and downloaded. Summarizing the text...')

                summary = await get_groq_response(caption_srt, system_prompt)
                await event.reply(f'Summary: {summary}')
            else:
                # Captions not available, fallback to audio transcription
                await event.reply('No captions found. Downloading audio from the YouTube video...')
                print("No captions found. Downloading audio from YouTube...")

                audio_stream = yt.streams.filter(only_audio=True).first()
                output_file = audio_stream.download(filename='audio.mp4')
                print(f"Downloaded audio to {output_file}")

                await event.reply('Converting audio to text...')
                print("Converting audio to text...")

                # Convert audio to text
                try:
                    with sr.AudioFile(output_file) as source:
                        recognizer.adjust_for_ambient_noise(source)
                        audio_data = recognizer.record(source)
                        try:
                            text = recognizer.recognize_google(audio_data)
                            print(f"Transcribed text: {text}")

                            # Summarize the transcribed text
                            await event.reply('Summarizing the text...')
                            summary = await get_groq_response(text, system_prompt)
                            print(f"Summary: {summary}")
                            await event.reply(f'Summary: {summary}')
                        except sr.RequestError:
                            print("API unavailable.")
                            await event.reply('API unavailable.')
                        except sr.UnknownValueError:
                            print("Unable to recognize speech.")
                            await event.reply('Unable to recognize speech.')
                except Exception as e:
                    print(f"Error during transcription: {str(e)}")
                    await event.reply(f'Error during transcription: {str(e)}')
                finally:
                    # Clean up files
                    if os.path.exists(output_file):
                        os.remove(output_file)
                        print(f"Deleted file: {output_file}")
        except Exception as e:
            print(f"Error: {str(e)}")
            await event.reply(f'Error: {str(e)}')
    else:
        print("Invalid YouTube link.")
        await event.reply('Please send a valid YouTube link.')

async def main():
    await client.start(bot_token=bot_token)
    print("Bot is running...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
