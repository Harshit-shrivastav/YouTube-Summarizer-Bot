import requests 
import asyncio 
import aiohttp 
import json
import sys

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


BASE_URL = "https://api.h-s.site"
def get_duckai_response(user_prompt, system_prompt):
    try:
        try:
            token_response = requests.get(f"{BASE_URL}/v1/get-token")
            token_response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error getting token: {e}")
            sys.exit(1)

        try:
            token = token_response.json()["token"]
        except KeyError:
            print("Error: 'token' key not found in the response.")
            sys.exit(1)
        except ValueError:
            print("Error: Invalid JSON response from the server.")
            sys.exit(1)

        payload = {
            "token": token,
            "model": "gpt-4o-mini",
            "message": [
                {"role": "user", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False
        }

        try:
            response = requests.post(f"{BASE_URL}/v1/chat/completions", json=payload)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error sending request to chat completions: {e}")
            sys.exit(1)

        try:
            response_data = response.json()
            content = response_data["choice"][0]["message"]["content"]
            return content
        except KeyError as e:
            print(f"Error: Missing expected key in the response - {e}")
            sys.exit(1)
        except IndexError:
            print("Error: No choices found in the response.")
            sys.exit(1)
        except ValueError:
            print("Error: Invalid JSON response from the server.")
            sys.exit(1)

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

