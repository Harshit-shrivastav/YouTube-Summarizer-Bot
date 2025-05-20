from google import genai
from google.genai import types

def get_gemini_response(api_key: str, system_prompt: str, user_prompt: str) -> str:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_prompt
        ),
        contents=user_prompt
    )
    
    return response.text
