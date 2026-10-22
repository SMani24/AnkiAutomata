import requests
import json
import re
import os
import tempfile
from html import escape
from pathlib import Path
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

CONFIG_FILE = Path(__file__).resolve().with_name('config.json')
REQUEST_TIMEOUT = (5, 15)

def load_config():
    global config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            if 'preferences' not in config:
                config['preferences'] = {}
            return config
    except FileNotFoundError:
        raise SystemExit(f"Error: Could not find '{CONFIG_FILE}'. Please create it beside engine.py.")

config = load_config()

def get_preference(key, default=None):
    return config.get('preferences', {}).get(key, default)

def save_preference(key, value):
    save_preferences({key: value})

def save_preferences(pref_dict):
    global config
    if 'preferences' not in config:
        config['preferences'] = {}
    config['preferences'].update(pref_dict)
    temp_path = None
    try:
        # Replace only after writing succeeds so an interrupted save keeps the config intact.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=Path(CONFIG_FILE).parent, delete=False) as f:
            temp_path = f.name
            json.dump(config, f, indent=4)
        os.replace(temp_path, CONFIG_FILE)
    except OSError as e:
        print(f"Error writing preferences to {CONFIG_FILE}: {e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

def invoke_anki(action, **params):
    payload = {'action': action, 'version': 6, 'params': params}
    http_response = requests.post(config['anki']['url'], json=payload, timeout=REQUEST_TIMEOUT)
    http_response.raise_for_status()
    response = http_response.json()
    if not isinstance(response, dict) or 'error' not in response or 'result' not in response:
        raise ValueError('Invalid response from AnkiConnect')
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
    open_tag = config['templates']['highlight_open_tag']
    close_tag = config['templates']['highlight_close_tag']
    return _highlight_text(word, sentence, open_tag, close_tag)

def bold_word(word, text):
    return _highlight_text(word, text, '<b>', '</b>')

def _highlight_text(word, text, open_tag, close_tag):
    """Escape plain editor text while retaining only the generated highlight tags."""
    if not text:
        return ""
    if not word:
        return escape(text)
    parts = []
    last = 0
    for match in re.finditer(re.escape(word), text, flags=re.IGNORECASE):
        parts.extend((escape(text[last:match.start()]), open_tag,
                      escape(match.group()), close_tag))
        last = match.end()
    parts.append(escape(text[last:]))
    return ''.join(parts)

def download_audio(url, headers):
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content

def group_senses(senses):
    """Groups senses that share the same Part of Speech and Guideword."""
    if not senses:
        return []

    groups = []
    group_map = {}

    for s in senses:
        pos = s.get('pos', '').strip()
        gw = s.get('guideword', '').strip()

        # If a guideword exists, group by (POS, Guideword)
        if gw:
            key = (pos.lower(), gw.upper())
        else:
            # Standalone sense without guideword
            key = ("__nogw__", len(groups))

        if key in group_map:
            grp = group_map[key]
            if s['definition'] not in grp['definitions']:
                grp['definitions'].append(s['definition'])
            for ex in s.get('examples', []):
                if ex not in grp['examples']:
                    grp['examples'].append(ex)
        else:
            new_grp = {
                "pos": pos,
                "guideword": gw,
                "definitions": [s['definition']],
                "examples": list(s.get('examples', []))
            }
            group_map[key] = new_grp
            groups.append(new_grp)

    return groups

def scrape_cambridge(word, manual_url=None):
    headers = {"User-Agent": config['scraper']['user_agent']}
    
    if manual_url:
        url = manual_url
    else:
        formatted_query = quote(word.strip().lower().replace(' ', '-'), safe='-')
        url = f"{config['scraper']['base_url']}{formatted_query}"
    
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    entries = soup.select('.pr.entry-body__el')
    if not entries:
        entries = soup.select('.entry-body__el')
        
    if not entries:
        return None

    senses = []
    all_examples = []
    seen_definitions = set()

    for entry in entries:
        entry_pos_el = entry.select_one('.pos-header .pos.dpos, .pos.dpos')
        default_pos = entry_pos_el.text.strip() if entry_pos_el else ""

        def_blocks = entry.select('.def-block.ddef_block')
        if not def_blocks:
            def_blocks = entry.select('.ddef_block')

        for block in def_blocks:
            def_element = block.select_one('.def.ddef_d')
            if not def_element:
                continue

            def_text = def_element.text.strip().rstrip(' :').strip()
            if not def_text:
                continue

            # Deduplicate repeated identical definitions across secondary dictionaries
            norm_key = re.sub(r'\s+', ' ', def_text.lower())
            if norm_key in seen_definitions:
                continue
            seen_definitions.add(norm_key)

            guideword = ""
            parent_sense = block.find_parent(class_='dsense')
            pos = default_pos

            if parent_sense:
                sense_pos_el = parent_sense.select_one('.pos.dpos')
                if sense_pos_el:
                    pos = sense_pos_el.text.strip()

                gw_element = parent_sense.select_one('.guideword, .dsense_gw')
                if gw_element:
                    raw_gw = gw_element.get_text().strip()
                    guideword = re.sub(r'^[(\s]+|[)\s]+$', '', raw_gw).strip()

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
            d_text = d.text.strip().rstrip(' :').strip()
            if d_text and d_text.lower() not in seen_definitions:
                seen_definitions.add(d_text.lower())
                senses.append({
                    "pos": "",
                    "guideword": "",
                    "definition": d_text,
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
    uk_audio = urljoin(url, uk_audio_source['src']) if (uk_audio_source and uk_audio_source.get('src')) else None
    us_audio = urljoin(url, us_audio_source['src']) if (us_audio_source and us_audio_source.get('src')) else None

    groups = group_senses(senses)

    return {
        "word": word,
        "senses": senses,
        "groups": groups,
        "definition": senses[0]["definition"] if senses else "No definition found.",
        "examples_raw": all_examples,
        "uk_ipa": uk_ipa,
        "us_ipa": us_ipa,
        "uk_audio": uk_audio,
        "us_audio": us_audio,
        "headers": headers
    }
