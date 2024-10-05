import os
from dotenv import load_dotenv

load_dotenv()

class Telegram:
    API_ID = int(os.environ.get('API_ID'))
    API_HASH = os.environ.get('API_HASH')
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    AUTH_USER_ID = int(os.environ.get('AUTH_USER_ID'))
    
class Ai:
    GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

class Database:
    REDIS_URI = os.environ.get('REDIS_URI')
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD')
