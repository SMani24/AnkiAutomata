import requests
from bs4 import BeautifulSoup

def scrape_cambridge(word):
    print(f"Searching for: {word}...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    url = f"https://dictionary.cambridge.org/dictionary/english/{word}"
    response = requests.get(url, headers=headers)
    
    if response.status_code != 200:
        print(f"Error: Could not reach Cambridge Dictionary (Status: {response.status_code})")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Isolate the FIRST dictionary entry on the page to avoid bloat and secondary meanings
    primary_entry = soup.select_one('.pr.entry-body__el')
    
    if not primary_entry:
        print("Could not find a valid dictionary entry for this word.")
        return None

    # 1. Extract the Definition
    def_element = primary_entry.select_one('.def.ddef_d')
    definition = def_element.text.strip() if def_element else "Definition not found"
    
    # 2. Extract the Phonetic Spelling (Explicitly UK)
    ipa_element = primary_entry.select_one('.uk .ipa.dipa')
    ipa = f"/{ipa_element.text.strip()}/" if ipa_element else "IPA not found"
    
    # 3. Extract the Audio URL (Explicitly UK)
    audio_source = primary_entry.select_one('.uk source[type="audio/mpeg"]')
    audio_url = None
    if audio_source and 'src' in audio_source.attrs:
        audio_url = "https://dictionary.cambridge.org" + audio_source['src']
        
    # 4. Extract Example Sentences
    # Find all example spans within this primary entry
    example_elements = primary_entry.select('.eg.deg')
    
    # Extract the text and limit it to the top 3 examples so the card isn't massive
    examples = [ex.text.strip() for ex in example_elements][:3]
    
    # Format the examples into a nice single string with bullet points
    formatted_examples = "\n".join([f"• {ex}" for ex in examples]) if examples else "No examples found."
        
    return {
        "word": word,
        "definition": definition,
        "ipa": ipa,
        "examples": formatted_examples,
        "audio_url": audio_url,
        "headers": headers
    }

# --- Test the function ---
if __name__ == "__main__":
    # Testing with retrospect to see the examples pull through
    target_word = "retrospect"
    data = scrape_cambridge(target_word)
    
    if data:
        print("\n--- Data Extracted ---")
        print(f"Word: {data['word']}")
        print(f"IPA:  {data['ipa']}")
        print(f"Def:  {data['definition']}")
        print(f"Examples:\n{data['examples']}")
        
        if data['audio_url']:
            print("\nDownloading audio...")
            audio_response = requests.get(data['audio_url'], headers=data['headers'])
            filename = f"{target_word}.mp3"
            with open(filename, 'wb') as f:
                f.write(audio_response.content)
            print(f"Success! Audio saved locally as '{filename}'")