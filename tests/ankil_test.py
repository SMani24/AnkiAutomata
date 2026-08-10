import requests

# AnkiConnect runs locally on port 8765 by default
url = 'http://127.0.0.1:8765'

# The JSON payload that tells Anki what to do
payload = {
    "action": "addNote",
    "version": 6,
    "params": {
        "note": {
            "deckName": "Default",  # Ensure you actually have a deck named "Default"
            "modelName": "Basic",   # Ensure you have a card type named "Basic"
            "fields": {
                "Front": "Hello from Python!",
                "Back": "It worked. AnkiConnect is listening."
            },
            "tags": ["automated_test"]
        }
    }
}

try:
    # Send the POST request to Anki
    response = requests.post(url, json=payload)
    
    # Print the response from Anki
    print("Response from Anki:")
    print(response.json())
    
except Exception as e:
    print(f"Failed to connect. Is Anki running? Error: {e}")