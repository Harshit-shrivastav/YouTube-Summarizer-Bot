import requests 
import asyncio 
import aiohttp 
import json


async def get_arliai_response(api_key: str, user_prompt: str, system_prompt: str):
    url = "https://api.arliai.com/v1/chat/completions"
    payload = json.dumps({
        "model": "Mistral-Nemo-12B-Instruct-2407",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    })
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f"Bearer {api_key}"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=payload) as response:
            if response.status == 200:
                try:
                    response_data = await response.json()
                    return response_data['choices'][0]['message']['content']
                except (json.JSONDecodeError, KeyError):
                    raise Exception("Error decoding API response.")
            else:
                raise Exception(f"API Error: {response.status} - {await response.text()}")

