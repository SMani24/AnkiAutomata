import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import base64
import json
import re
from bs4 import BeautifulSoup

# --- Load Configuration ---
CONFIG_FILE = 'config.json'

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Could not find '{CONFIG_FILE}'. Please create it in the same directory.")
    exit(1)

# --- Modern UI Setup ---
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# --- Core Logic Functions ---
def invoke_anki(action, **params):
    payload = {'action': action, 'version': 6, 'params': params}
    response = requests.post(config['anki']['url'], json=payload).json()
    if response.get('error'):
        raise Exception(response['error'])
    return response.get('result')

def get_anki_decks():
    """Fetches all live deck names from Anki"""
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
    ipa_element = primary_entry.select_one('.uk .ipa.dipa')
    audio_source = primary_entry.select_one('.uk source[type="audio/mpeg"]')
    example_elements = primary_entry.select('.eg.deg')
    
    definition = def_element.text.strip() if def_element else "No definition found."
    ipa = f"/{ipa_element.text.strip()}/" if ipa_element else ""
    audio_url = "https://dictionary.cambridge.org" + audio_source['src'] if (audio_source and 'src' in audio_source.attrs) else None
    
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

# --- Custom Hierarchy Dialog ---
class DeckSelectionDialog(ctk.CTkToplevel):
    def __init__(self, parent, decks, current_deck):
        super().__init__(parent)
        self.title("Select Anki Deck")
        self.geometry("400x500")
        self.selected_deck = current_deck
        
        # Make the dialog modal (blocks main window)
        self.transient(parent)
        self.grab_set()
        
        # Style the standard Treeview to match CTk Theme
        style = ttk.Style(self)
        mode = ctk.get_appearance_mode()
        
        if mode == "Dark":
            bg_color = "#2b2b2b"
            text_color = "#dce4ee"
            sel_bg = "#1f538d"
        else:
            bg_color = "#ebebeb"
            text_color = "#000000"
            sel_bg = "#3b8ed0"
            
        style.theme_use("default")
        style.configure("Treeview", 
                        background=bg_color, 
                        foreground=text_color, 
                        fieldbackground=bg_color, 
                        borderwidth=0,
                        rowheight=25)
        style.map('Treeview', background=[('selected', sel_bg)])

        # Treeview Widget
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(expand=True, fill="both", padx=15, pady=(15, 5))
        
        # Populate with hierarchy
        self.populate_tree(decks)
        
        # Action Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkButton(btn_frame, text="Select", command=self.confirm).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy, fg_color="transparent", border_width=1).pack(side="right")

    def populate_tree(self, decks):
        # Sort to ensure parent categories are created before subdecks
        decks.sort()
        inserted_nodes = {}
        
        for deck in decks:
            parts = deck.split("::")
            for i in range(1, len(parts) + 1):
                node_id = "::".join(parts[:i])
                if node_id not in inserted_nodes:
                    parent_id = "::".join(parts[:i-1]) if i > 1 else ""
                    display_text = parts[i-1]
                    self.tree.insert(parent_id, "end", iid=node_id, text=display_text, open=True)
                    inserted_nodes[node_id] = True
        
        # Highlight currently selected deck
        if self.selected_deck in inserted_nodes:
            self.tree.selection_set(self.selected_deck)
            self.tree.see(self.selected_deck)

    def confirm(self):
        selection = self.tree.selection()
        if selection:
            self.selected_deck = selection[0]
        self.destroy()

# --- GUI Implementation ---
class AnkiAutomataApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("AnkiAutomata")
        self.geometry("550x550")
        self.grid_columnconfigure(1, weight=1)
        
        # Header
        self.header = ctk.CTkLabel(self, text="AnkiAutomata ⚙️", font=ctk.CTkFont(size=20, weight="bold"))
        self.header.grid(row=0, column=0, columnspan=2, padx=20, pady=(20, 15), sticky="w")
        
        # Deck Selection Row
        self.deck_label = ctk.CTkLabel(self, text="Target Deck:")
        self.deck_label.grid(row=1, column=0, padx=20, pady=10, sticky="w")
        
        self.deck_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.deck_frame.grid(row=1, column=1, padx=20, pady=10, sticky="ew")
        self.deck_frame.grid_columnconfigure(0, weight=1)
        
        self.deck_var = tk.StringVar(value=config['anki']['default_deck'])
        self.deck_display = ctk.CTkEntry(self.deck_frame, textvariable=self.deck_var, state="readonly")
        self.deck_display.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        
        self.deck_btn = ctk.CTkButton(self.deck_frame, text="Change", width=70, command=self.change_deck)
        self.deck_btn.grid(row=0, column=1)
        
        # Word Input
        self.word_label = ctk.CTkLabel(self, text="Target Word:")
        self.word_label.grid(row=2, column=0, padx=20, pady=10, sticky="w")
        self.word_var = tk.StringVar()
        self.word_entry = ctk.CTkEntry(self, textvariable=self.word_var, placeholder_text="e.g. serendipity")
        self.word_entry.grid(row=2, column=1, padx=20, pady=10, sticky="ew")
        
        # Sentence Input
        self.sentence_label = ctk.CTkLabel(self, text="Book Sentence:")
        self.sentence_label.grid(row=3, column=0, padx=20, pady=10, sticky="nw")
        self.sentence_text = ctk.CTkTextbox(self, height=80)
        self.sentence_text.grid(row=3, column=1, padx=20, pady=10, sticky="ew")
        
        # Add Button
        self.add_btn = ctk.CTkButton(self, text="Add Card to Anki", command=self.process_card, height=40)
        self.add_btn.grid(row=4, column=0, columnspan=2, padx=20, pady=20, sticky="ew")
        
        # Status/Log Output
        self.log_area = ctk.CTkTextbox(self, height=120, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_area.grid(row=5, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")
        self.log_area.insert("0.0", "System ready. Waiting for input...\n")
        self.log_area.configure(state="disabled")
        
        # Bind Enter key
        self.word_entry.bind('<Return>', lambda event: self.process_card())
        self.word_entry.focus()

    def change_deck(self):
        """Spawns the hierarchical deck selection modal"""
        available_decks = get_anki_decks()
        current = self.deck_var.get()
        
        if current not in available_decks:
            available_decks.append(current)
            
        dialog = DeckSelectionDialog(self, available_decks, current)
        self.wait_window(dialog)  # Pause until the user closes the modal
        
        if dialog.selected_deck:
            self.deck_var.set(dialog.selected_deck)

    def log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")
        self.update()

    def process_card(self):
        deck = self.deck_var.get().strip()
        word = self.word_var.get().strip()
        sentence = self.sentence_text.get("1.0", tk.END).strip()
        
        if not word:
            self.log("[!] Please enter a target word.")
            return
            
        self.log(f"\n--- Processing '{word}' ---")
        
        try:
            if is_duplicate(word, deck):
                self.log(f"[!] Skipped: '{word}' already exists in '{deck}'.")
                return
        except Exception as e:
            self.log(f"[!] AnkiConnect Error: {e}")
            messagebox.showerror("Connection Error", "Make sure Anki is open and the AnkiConnect add-on is installed.")
            return

        self.log("Scraping Cambridge dictionary...")
        data = scrape_cambridge(word)
        
        if not data:
            dialog = ctk.CTkInputDialog(text=f"Could not find an entry for '{word}'.\nPaste a direct Cambridge URL:", title="Manual Entry Required")
            manual_url = dialog.get_input()
            if manual_url:
                self.log("Retrying with manual URL...")
                data = scrape_cambridge(word, manual_url=manual_url.strip())
            
        if not data:
            self.log(f"[!] Skipped '{word}'. No data found.")
            return
            
        audio_filename = f"ankiautomata_{word.replace(' ', '_')}.mp3"
        audio_tag = ""
        if data['audio_url']:
            try:
                audio_req = requests.get(data['audio_url'], headers=data['headers'])
                audio_base64 = base64.b64encode(audio_req.content).decode('utf-8')
                invoke_anki('storeMediaFile', filename=audio_filename, data=audio_base64)
                audio_tag = f"[sound:{audio_filename}]"
            except Exception as e:
                self.log(f"[!] Warning: Failed to process audio - {e}")
        
        bolded_definition = bold_word(word, data['definition'])
        bolded_examples = bold_word(word, data['examples'])
        
        front_html = config['templates']['front'].format(word=word)
        highlighted_sentence = format_sentence(word, sentence)
        back_html = config['templates']['back_layout'].format(
            definition=bolded_definition, 
            examples=bolded_examples
        )
        
        note = {
            "deckName": deck,
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
            self.log(f"[+] SUCCESS! Added '{word}' to {deck}.")
            
            self.word_var.set("")
            self.sentence_text.delete("1.0", tk.END)
            self.word_entry.focus()
            
        except Exception as e:
            self.log(f"[!] Failed to add note: {e}")

if __name__ == "__main__":
    app = AnkiAutomataApp()
    app.mainloop()