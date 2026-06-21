import requests
from dotenv import load_dotenv
import os

load_dotenv()

API_KEY = os.getenv("HYPIXEL_API_KEY")

def get_election_data():
    url = "https://api.hypixel.net/v2/resources/skyblock/election"

    headers = {
        "API-Key": API_KEY
    }

    response = requests.get(url, headers=headers)

    return response.json()