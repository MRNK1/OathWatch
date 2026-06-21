import json

WORLD_FILE = "data/world_state.json"

def load_world_state():
    try:
        with open(WORLD_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def save_world_state(data):
    with open(WORLD_FILE, "w") as f:
        json.dump(data, f, indent=4)