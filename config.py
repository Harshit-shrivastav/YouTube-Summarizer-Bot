import os
from dotenv import load_dotenv

load_dotenv()

class Telegram:
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    AUTH_USER_ID = int(os.environ.get('AUTH_USER_ID'))
    
class Ai:
    API_KEY = os.environ.get('AI_API_KEY')  # This is now optional
    MODEL_NAME = os.environ.get('AI_MODEL_NAME', 'openai')  # Default to 'openai'
    API_URL = os.environ.get('AI_API_URL', 'https://text.pollinations.ai/openai')  # Default to pollinations
    
class Database:
    REDIS_HOST = os.environ.get('REDIS_HOST')
    REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
