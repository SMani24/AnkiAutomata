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
git clone [https://github.com/yourusername/AnkiAutomata.git](https://github.com/yourusername/AnkiAutomata.git)
cd AnkiAutomata

# Create and activate the virtual environment
python3 -m venv envAnkiAutomata
source envAnkiAutomata/bin/activate  # On Windows use: envAnkiAutomata\Scripts\activate

# Install required dependencies
pip install requests beautifulsoup4