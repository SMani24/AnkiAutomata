import requests
import json
import re
from bs4 import BeautifulSoup

CONFIG_FILE = 'config.json'

def load_config():
    global config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            if 'preferences' not in config:
                config['preferences'] = {}
            return config
    except FileNotFoundError:
        print(f"Error: Could not find '{CONFIG_FILE}'. Please create it in the same directory.")
        exit(1)

config = load_config()

def get_preference(key, default=None):
    return config.get('preferences', {}).get(key, default)

def save_preference(key, value):
    global config
    if 'preferences' not in config:
        config['preferences'] = {}
    config['preferences'][key] = value
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error writing preference to {CONFIG_FILE}: {e}")

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
    entries = soup.select('.pr.entry-body__el')
    if not entries:
        entries = soup.select('.entry-body__el')
        
    if not entries:
        return None

    senses = []
    all_examples = []

    for entry in entries:
        pos_element = entry.select_one('.pos-header .pos.dpos, .pos.dpos')
        pos = pos_element.text.strip() if pos_element else ""

        def_blocks = entry.select('.def-block.ddef_block')
        if not def_blocks:
            def_blocks = entry.select('.ddef_block')

        for block in def_blocks:
            def_element = block.select_one('.def.ddef_d')
            if not def_element:
                continue

            def_text = def_element.text.strip().rstrip(' :').strip()

            guideword = ""
            parent_sense = block.find_parent(class_='dsense')
            if parent_sense:
                gw_element = parent_sense.select_one('.guideword, .dsense_h')
                if gw_element:
                    guideword = gw_element.text.strip()

            example_elements = block.select('.eg.deg')
            block_examples = [ex.text.strip() for ex in example_elements if ex.text.strip()]

            for ex in block_examples:
                if ex not in all_examples:
                    all_examples.append(ex)

            senses.append({
                "pos": pos,
                "guideword": guideword,
                "definition": def_text,
                "examples": block_examples
            })

    if not senses:
        fallback_defs = soup.select('.def.ddef_d')
        fallback_examples = [ex.text.strip() for ex in soup.select('.eg.deg') if ex.text.strip()]
        for d in fallback_defs:
            senses.append({
                "pos": "",
                "guideword": "",
                "definition": d.text.strip().rstrip(' :').strip(),
                "examples": fallback_examples
            })
        all_examples = fallback_examples

    if not senses:
        return None

    uk_ipa_element = soup.select_one('.uk .ipa.dipa')
    uk_audio_source = soup.select_one('.uk source[type="audio/mpeg"]')
    
    us_ipa_element = soup.select_one('.us .ipa.dipa')
    us_audio_source = soup.select_one('.us source[type="audio/mpeg"]')
    
    uk_ipa = f"/{uk_ipa_element.text.strip()}/" if uk_ipa_element else ""
    us_ipa = f"/{us_ipa_element.text.strip()}/" if us_ipa_element else ""
    uk_audio = "https://dictionary.cambridge.org" + uk_audio_source['src'] if (uk_audio_source and 'src' in uk_audio_source.attrs) else None
    us_audio = "https://dictionary.cambridge.org" + us_audio_source['src'] if (us_audio_source and 'src' in us_audio_source.attrs) else None

    return {
        "word": word,
        "senses": senses,
        "definition": senses[0]["definition"] if senses else "No definition found.",
        "examples_raw": all_examples,
        "uk_ipa": uk_ipa,
        "us_ipa": us_ipa,
        "uk_audio": uk_audio,
        "us_audio": us_audio,
        "headers": headers
    }