import requests
import base64
import json
import re
import os
from bs4 import BeautifulSoup

# --- Load Configuration ---
CONFIG_FILE = 'config.json'

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Could not find '{CONFIG_FILE}'. Please create it in the same directory.")
    exit(1)

def clear_screen():
    """Clears the terminal screen for a cleaner UI"""
    os.system('cls' if os.name == 'nt' else 'clear')

def invoke_anki(action, **params):
    """Helper function to talk to AnkiConnect"""
    payload = {'action': action, 'version': 6, 'params': params}
    response = requests.post(config['anki']['url'], json=payload).json()
    if response.get('error'):
        raise Exception(response['error'])
    return response.get('result')

def is_duplicate(word, deck_name):
    """Queries Anki to see if the word already exists in the target deck"""
    query = f'deck:"{deck_name}" "{word}"'
    existing_notes = invoke_anki('findNotes', query=query)
    return len(existing_notes) > 0

def format_sentence(word, sentence):
    """Highlights the target word in RED and BOLD for the Front"""
    if not sentence:
        return ""
    open_tag = config['templates']['highlight_open_tag']
    close_tag = config['templates']['highlight_close_tag']
    styled_replacement = f"{open_tag}\\g<0>{close_tag}"
    return re.sub(rf"(?i)({re.escape(word)})", styled_replacement, sentence)

def bold_word(word, text):
    """Applies standard BOLDing to the target word for the Back"""
    if not text:
        return ""
    return re.sub(rf"(?i)({re.escape(word)})", r"<b>\g<0></b>", text)

def scrape_cambridge(word, manual_url=None):
    """Scrapes the Cambridge Dictionary using config settings or a manual URL"""
    print(f"  -> Scraping Cambridge data...")
    headers = {"User-Agent": config['scraper']['user_agent']}
    
    # Handle casing and spaces for the URL if no manual URL is provided
    if manual_url:
        url = manual_url
    else:
        formatted_query = word.lower().replace(' ', '-')
        url = f"{config['scraper']['base_url']}{formatted_query}"
    
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    primary_entry = soup.select_one('.pr.entry-body__el')
    
    if not primary_entry:
        return None

    # Extract Data
    def_element = primary_entry.select_one('.def.ddef_d')
    ipa_element = primary_entry.select_one('.uk .ipa.dipa')
    audio_source = primary_entry.select_one('.uk source[type="audio/mpeg"]')
    example_elements = primary_entry.select('.eg.deg')
    
    definition = def_element.text.strip() if def_element else "No definition found."
    ipa = f"/{ipa_element.text.strip()}/" if ipa_element else ""
    audio_url = "https://dictionary.cambridge.org" + audio_source['src'] if (audio_source and 'src' in audio_source.attrs) else None
    
    # Format Cambridge Examples
    examples = [ex.text.strip() for ex in example_elements][:3]
    bullet_template = config['templates']['example_bullet']
    separator = config['templates']['example_separator']
    
    formatted_examples_list = [bullet_template.format(example=ex) for ex in examples]
    formatted_examples_string = separator.join(formatted_examples_list) if examples else ""
    
    return {
        "word": word,
        "definition": definition,
        "ipa": ipa,
        "examples": formatted_examples_string,
        "audio_url": audio_url,
        "headers": headers
    }

def setup_session_deck():
    """Asks for the deck once at startup"""
    clear_screen()
    print("=========================================")
    print("         AnkiAutomata Setup              ")
    print("=========================================\n")
    default_deck = config['anki']['default_deck']
    user_input = input(f"Enter target deck [{default_deck}]: ").strip()
    return user_input if user_input else default_deck

def interactive_loop():
    """Runs a continuous prompt for seamless input while reading"""
    current_deck = setup_session_deck()
    
    while True:
        clear_screen()
        print(f"=== AnkiAutomata | Deck: {current_deck} ===")
        print("Type 'quit' or 'exit' to stop.\n")
        
        word = input("Target Word: ").strip()
        if word.lower() in ['quit', 'exit']:
            break
        if not word:
            continue
            
        if is_duplicate(word, current_deck):
            print(f"\n  [!] Skipping: '{word}' already exists in '{current_deck}'.")
            input("\nPress Enter to continue...")
            continue
            
        sentence = input("Book Sentence (optional): ").strip()
        if sentence.lower() in ['quit', 'exit']:
            break
            
        data = scrape_cambridge(word)
        
        # Manual URL Fallback Logic
        if not data:
            print(f"\n  [!] Could not find an entry for '{word}'.")
            manual_url = input("      Paste a direct Cambridge URL (or press Enter to skip): ").strip()
            if manual_url:
                data = scrape_cambridge(word, manual_url=manual_url)
            
        if not data:
            print(f"  [!] Skipping '{word}'.")
            input("\nPress Enter to continue...")
            continue
            
        # Handle Audio
        audio_filename = f"ankiautomata_{word.replace(' ', '_')}.mp3"
        audio_tag = ""
        if data['audio_url']:
            audio_req = requests.get(data['audio_url'], headers=data['headers'])
            audio_base64 = base64.b64encode(audio_req.content).decode('utf-8')
            invoke_anki('storeMediaFile', filename=audio_filename, data=audio_base64)
            audio_tag = f"[sound:{audio_filename}]"
        
        # Apply standard bolding to the back-of-card text
        bolded_definition = bold_word(word, data['definition'])
        bolded_examples = bold_word(word, data['examples'])
        
        # Format HTML payload
        front_html = config['templates']['front'].format(word=word)
        highlighted_sentence = format_sentence(word, sentence)
        back_html = config['templates']['back_layout'].format(
            definition=bolded_definition, 
            examples=bolded_examples
        )
        
        note = {
            "deckName": current_deck,
            "modelName": config['anki']['model_name'],
            "fields": {
                "Front": front_html,
                "Example sentence": highlighted_sentence,
                "Pronounciation": f"{data['ipa']} {audio_tag}",
                "Back": back_html
            },
            "options": {
                "allowDuplicate": False
            },
            "tags": config['anki']['tags']
        }
        
        try:
            invoke_anki('addNote', note=note)
            print(f"\n  [+] SUCCESS! '{word}' added to {current_deck}.")
        except Exception as e:
            print(f"\n  [!] Failed to add note to Anki: {e}")
            
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    interactive_loop()