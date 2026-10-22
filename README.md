# AnkiAutomata ⚙️

AnkiAutomata is a modern desktop GUI and background automation client designed to instantly bridge the gap between your reading workflow and your Anki database.

Built with CustomTkinter, it captures target words directly from your clipboard or OS hotkeys, scrapes definitions, guidewords, examples, and native UK/US audio from Cambridge Dictionary, and formats clean, bolded HTML flashcards straight into your Anki decks via AnkiConnect.

---

## ✨ Features

### 📖 Intelligent Scraping & Semantic Grouping

* **Comprehensive Multi-Sense Extraction:** Scrapes all definitions and examples across the Cambridge Dictionary without arbitrary truncation limits.
* **Semantic Sense Grouping:** Automatically groups related definitions that share the same Part of Speech and Guideword (e.g., `[noun] (CONTAINER)` or `[noun] (LOW POINT)`), formatting distinct sub-senses as nested lettered lists (`a.`, `b.`, `c.`).
* **Interactive Sense Selector:** Choose between specific numbered meaning groups via a dropdown or select **"📚 All Meanings & Examples"** to merge every sense into a structured card.
* **Smart Deduplication:** Filters out redundant dictionary entries from secondary on-page learner/business glossaries while checking Anki in real time to prevent duplicate cards.



### 🖥️ Modern, Adaptive GUI

* **Dual-Axis Resizable Splitters:**
* **Horizontal Splitter:** Drag the splitter bar between the **Definition** and **Examples** panes to customize editor proportions. Features a smart auto-shrink engine that automatically contracts the definition box for short definitions while respecting your preferred maximum height.
* **Vertical Splitter:** Drag the divider between the left control panel and the right dictionary editor to set custom column proportions.


* **Dynamic Text Scaling:** Scale UI typography on the fly between **Normal (100%)**, **Medium (115%)**, **Large (130%)**, and **XL (145%)**.
* **Fixed-Padding Geometry:** Column containers resize cleanly across full-screen and compact window layouts without excessive gaps between cards.
* **Persistent Preferences:** Automatically saves window dimensions, vertical and horizontal splitter positions, preferred text scale, last-used deck, auto-combine preferences, and audio region to `config.json`.

### 🔊 Audio & Card Formatting

* **Dual-Region Audio & IPA:** Scrapes UK and US phonetic IPA alongside direct MP3 pronunciations.


* **In-Memory Audio Preview:** Listen to UK and US native pronunciations inside the app prior to export.


* **Automated Media Sync:** Selected audio is encoded in Base64 and stored directly into Anki's media collection via AnkiConnect (`storeMediaFile`).


* **Clean Anki HTML:** Converted newlines (`<br>`) and sub-definition indentation (`&nbsp;`) prevent card styling issues in Anki, while preserving custom target-word bolding and sentence highlights.



### ⚡ Seamless OS Integration & Productivity

* **Search Selected PDF Text:** Highlight a word or phrase and press **Ctrl+Alt+W** on Linux. The shortcut captures the selection without changing your clipboard, opens or focuses AnkiAutomata, and searches immediately.
* **Global Shortcut Listener (IPC):** A local server (`127.0.0.1:24536`) accepts selected-text lookups and the original clipboard trigger.


* **Fast Window Close:** Use `Ctrl+W` (or `Cmd+W` on macOS) to instantly dismiss the window from any focused element while persisting all layout geometry.
* **Hierarchical Deck Selector:** Interactive tree-view modal for selecting nested sub-decks separated by `::`.



---

## 📋 Prerequisites

1. **Python 3.10+** installed on your machine.
2. **Anki Desktop** running locally.


3. **AnkiConnect Add-on** installed in Anki:


* In Anki, navigate to **Tools > Add-ons > Get Add-ons...**

* Enter add-on code: `2055492159`

* Restart Anki (AnkiConnect listens by default at `[http://127.0.0.1:8765](http://127.0.0.1:8765)`).





---

## 🚀 Installation

1. Clone the repository:
```bash
git clone https://github.com/SMani24/AnkiAutomata.git
cd AnkiAutomata

```


2. Create and activate a virtual environment:
```bash
python3 -m venv envAnkiAutomata
source envAnkiAutomata/bin/activate  # On Windows: envAnkiAutomata\Scripts\activate

```


3. Install required dependencies:


```bash
pip install customtkinter requests beautifulsoup4 pyperclip pygame

```



---

## ⚙️ Configuration (`config.json`)

Configure your card model, deck, field names, and card layout templates in `config.json`. Ensure `"model_name"` and `"fields"` in `main.py` align with your active Anki Note Type.

```json
{
  "anki": {
    "url": "http://127.0.0.1:8765",
    "default_deck": "English::Vocabulary",
    "model_name": "English words",
    "tags": ["AnkiAutomata"]
  },
  "scraper": {
    "base_url": "https://dictionary.cambridge.org/dictionary/english/",
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
  },
  "templates": {
    "front": "<b>{word}</b>",
    "highlight_open_tag": "<b style=\"color:#e63946;\">",
    "highlight_close_tag": "</b>",
    "example_bullet": "• {example}",
    "example_separator": "<br><br>",
    "back_layout": "<div style=\"text-align: left;\"><b>Meaning:</b> {definition}<br><br>{examples}</div>"
  },
  "preferences": {
    "font_scale": "Normal (100%)",
    "auto_all_meanings": false,
    "audio_choice": "uk",
    "selected_deck": "English::Vocabulary",
    "window_width": 1040,
    "window_height": 720,
    "user_def_height": 120,
    "user_left_width": 380
  }
}

```

> **Note:** The `"preferences"` object is generated and maintained automatically by the application as you interact with the UI.

---

## 💻 Usage

1. Launch Anki desktop.
2. Start the application:


```bash
python3 main.py

```


3. **Manual Entry:** Type a word into the target word box and press **Enter** (or click 🔍).


4. **Sentence Context (Optional):** Paste a sentence containing the word into the **Sentence** box. The word will be highlighted automatically when added to Anki.


5. **Review & Edit:**
* Pick a definition group from the dropdown or toggle **Auto-combine All**.


* Edit definitions or examples directly inside the text editors.


* Press **Enter** in the examples editor to add a new bullet point (`• `) automatically.


* Drag the horizontal or vertical splitters to re-apportion editor and panel sizes.


6. **Audio & Export:**
* Click **▶ UK Play** or **▶ US Play** to audition the pronunciations.


* Select your preferred audio track radio button and click **➕ Confirm & Add to Anki**.





---

## ⚡ Search selected text with a shortcut

On GNOME or Pop!_OS, activate your virtual environment and install the desktop shortcut once:

```bash
source envAnkiAutomata/bin/activate
python shortcut.py --install
```

This registers **Ctrl+Alt+W**, or repairs an existing **AnkiAutomata Search** shortcut while preserving its key combination and other desktop shortcuts. Run it again if you move the repository or virtual environment. Restart AnkiAutomata after updating the code.

1. Keep Anki Desktop running with AnkiConnect enabled.
2. Highlight a word or short phrase in your PDF reader (or another application that exposes its text selection).
3. Press **Ctrl+Alt+W**. AnkiAutomata opens or comes to the foreground and searches the selected text. You do not need to press **Ctrl+C**; your clipboard is preserved.

The helper uses `xclip` on X11 and `wl-paste` on Wayland. Install the appropriate package if needed (`sudo apt install xclip` or `sudo apt install wl-clipboard`). Wayland selection support depends on the compositor and PDF reader. Scanned PDFs need a selectable text layer.

For another Linux desktop, add a custom shortcut in Keyboard Settings whose command uses the absolute paths to your virtual environment's Python and `shortcut.py`. To check the selection helper manually, highlight text and run `python shortcut.py`.

### Existing clipboard trigger

You can still copy a word with **Ctrl+C** and trigger an already running AnkiAutomata instance using:

```bash
curl -s http://127.0.0.1:24536/
```

Other applications can submit selected text with a UTF-8 JSON `POST` to `http://127.0.0.1:24536/lookup`, for example `{"text": "retrospect"}`. Requests are queued for the GUI thread; selections are limited to 4 KB.

## Development checks

Run the offline regression suite from the repository root with the virtual environment activated:

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
```

These tests use mocked external responses and a temporary loopback HTTP server. They do not require Anki, Cambridge access, an audio device, or a desktop display. `tests/ankil_test.py` and `tests/scraper_test.py` are manual integration scripts; running the Anki script explicitly creates a note in your local collection.

The application loads `config.json` beside `engine.py`, so launching `main.py` from another working directory also works. Preference saves replace the config file only after writing succeeds. Network requests have connection and read timeouts, and audio playback initializes the device only when requested.
