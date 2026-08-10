# AnkiAutomata ⚙️

A lightweight, interactive command-line tool that bridges the gap between your reading material and your Anki database. 

AnkiAutomata eliminates the tedious process of manually creating vocabulary flashcards. By simply typing a target word and pasting a sentence from your book, this script scrapes the Cambridge Dictionary, downloads the native pronunciation audio, formats the HTML, and pushes the fully-assembled card directly to your local Anki deck.

## ✨ Features

* **Interactive Reading Mode:** Runs in a continuous terminal loop. Keep it open beside your book or PDF and add cards in seconds without breaking your flow.
* **Automated Data Extraction:** Pulls the primary definition, UK phonetic spelling (IPA), and top sample sentences directly from Cambridge.
* **Seamless Audio Integration:** Bypasses browser inspect-tools to automatically download the `.mp3` pronunciation and embed it into Anki's media folder via Base64 encoding.
* **Smart Text Formatting:** Automatically highlights the target word in your custom book sentence (bold/red) and applies standard bolding to the word in the dictionary definitions, preserving original capitalization.
* **Duplicate Prevention:** Queries your Anki database in real-time to warn you if a word already exists in your deck before making unnecessary web requests.
* **Highly Configurable:** Fully decoupled logic. Change target decks, Note Types, field mappings, and HTML styling purely through a `config.json` file.

## 📋 Prerequisites

1. **Python 3.x** installed on your system.
2. **Anki** desktop application installed and running.
3. **AnkiConnect Add-on** installed in Anki:
   * Open Anki > Tools > Add-ons > Get Add-ons...
   * Paste the code: `2055492159`
   * **Restart Anki.** (AnkiConnect runs locally on port `8765`).

## 🚀 Installation

Clone the repository and set up your virtual environment:

```bash
git clone [https://github.com/SMani24/AnkiAutomata.git](https://github.com/SMani24/AnkiAutomata.git)
cd AnkiAutomata

# Create and activate the virtual environment
python3 -m venv envAnkiAutomata
source envAnkiAutomata/bin/activate  # On Windows use: envAnkiAutomata\Scripts\activate

# Install required dependencies
pip install requests beautifulsoup4
<<<<<<< HEAD
```

## ⚙️ Configuration

Before running the script, ensure your `config.json` file matches your specific Anki setup. 

**Crucial Step:** The `"model_name"` and the dictionary keys under `"fields"` in `main.py` must perfectly match the Note Type and field names in your Anki database (e.g., `"Front"`, `"Example sentence"`, `"Pronounciation"`, `"Back"`).

```json
{
  "anki": {
    "url": "[http://127.0.0.1:8765](http://127.0.0.1:8765)",
    "default_deck": "University::RL",
    "model_name": "English words",
    "tags": ["AnkiAutomata"]
  },
  "templates": {
    "front": "<b>{word}</b>",
    "highlight_open_tag": "<b style=\"color:red;\">",
    "highlight_close_tag": "</b>",
    "example_bullet": "• {example}",
    "example_separator": "<br><br>",
    "back_layout": "<div style=\"text-align: left;\"><b>Meaning:</b> {definition}<br><br>{examples}</div>"
  }
}
```

## 💻 Usage

Make sure Anki is open in the background, then run the script:

```bash
python3 main.py
```

**Example Session:**
```text
=========================================
         AnkiAutomata Setup              
=========================================

Enter target deck [University::RL]: 

=== AnkiAutomata | Deck: University::RL ===
Type 'quit' or 'exit' to stop.

Target Word: serendipity
Book Sentence (optional): We found the optimal pathfinding trajectory purely by serendipity.
  -> Scraping Cambridge data...

  [+] SUCCESS! 'serendipity' added to University::RL.

Press Enter to continue...
```

## ⚠️ Notes & Fallbacks
* If a word is not found on Cambridge due to a complex variation, the tool will pause and allow you to manually paste a direct URL to the correct dictionary page.
* To exit the interactive loop, simply type `quit` or `exit` at any prompt.
=======
>>>>>>> 988803a60de605206ba83dade0ae065a1611cce2
