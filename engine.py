import requests
import json
import re
from bs4 import BeautifulSoup

CONFIG_FILE = 'config.json'

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Could not find '{CONFIG_FILE}'. Please create it in the same directory.")
    exit(1)

def invoke_anki(action, **params):
    payload = {'action': action, 'version': 6, 'params': params}
    response = requests.post(config['anki']['url'], json=payload).json()
    if response.get('error'):
        raise Exception(response['error'])
    return response.get('result')

def get_anki_decks():
    try:
        return invoke_anki('deckNames')
    except Exception:
        return [config['anki']['default_deck']]

def is_duplicate(word, deck_name):
    query = f'deck:"{deck_name}" "{word}"'
    existing_notes = invoke_anki('findNotes', query=query)
    return len(existing_notes) > 0

def format_sentence(word, sentence):
    if not sentence:
        return ""
    open_tag = config['templates']['highlight_open_tag']
    close_tag = config['templates']['highlight_close_tag']
    styled_replacement = f"{open_tag}\\g<0>{close_tag}"
    return re.sub(rf"(?i)({re.escape(word)})", styled_replacement, sentence)

def bold_word(word, text):
    if not text:
        return ""
    return re.sub(rf"(?i)({re.escape(word)})", r"<b>\g<0></b>", text)

def scrape_cambridge(word, manual_url=None):
    headers = {"User-Agent": config['scraper']['user_agent']}
    
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

    def_element = primary_entry.select_one('.def.ddef_d')
    example_elements = primary_entry.select('.eg.deg')
    
    uk_ipa_element = primary_entry.select_one('.uk .ipa.dipa')
    uk_audio_source = primary_entry.select_one('.uk source[type="audio/mpeg"]')
    
    us_ipa_element = primary_entry.select_one('.us .ipa.dipa')
    us_audio_source = primary_entry.select_one('.us source[type="audio/mpeg"]')
    
    definition = def_element.text.strip() if def_element else "No definition found."
    uk_ipa = f"/{uk_ipa_element.text.strip()}/" if uk_ipa_element else ""
    us_ipa = f"/{us_ipa_element.text.strip()}/" if us_ipa_element else ""
    uk_audio = "https://dictionary.cambridge.org" + uk_audio_source['src'] if (uk_audio_source and 'src' in uk_audio_source.attrs) else None
    us_audio = "https://dictionary.cambridge.org" + us_audio_source['src'] if (us_audio_source and 'src' in us_audio_source.attrs) else None
    
    examples = [ex.text.strip() for ex in example_elements][:3]
    
    return {
        "word": word,
        "definition": definition,
        "uk_ipa": uk_ipa,
        "us_ipa": us_ipa,
        "uk_audio": uk_audio,
        "us_audio": us_audio,
        "examples_raw": examples,
        "headers": headers
    }