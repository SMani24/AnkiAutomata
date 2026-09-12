import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import base64
import pyperclip
import io
import pygame
import socket
import threading
import engine

pygame.mixer.init()
ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class DeckSelectionDialog(ctk.CTkToplevel):
    def __init__(self, parent, decks, current_deck):
        super().__init__(parent)
        self.title("Select Anki Deck")
        self.geometry("400x500")
        self.selected_deck = current_deck
        
        self.transient(parent)
        self.grab_set()
        
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
        style.configure("Treeview", background=bg_color, foreground=text_color, 
                        fieldbackground=bg_color, borderwidth=0, rowheight=25)
        style.map('Treeview', background=[('selected', sel_bg)])

        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(expand=True, fill="both", padx=15, pady=(15, 5))
        
        self.populate_tree(decks)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkButton(btn_frame, text="Select", command=self.confirm).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy, fg_color="transparent", border_width=1).pack(side="right")

    def populate_tree(self, decks):
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
        
        if self.selected_deck in inserted_nodes:
            self.tree.selection_set(self.selected_deck)
            self.tree.see(self.selected_deck)

    def confirm(self):
        selection = self.tree.selection()
        if selection:
            self.selected_deck = selection[0]
        self.destroy()

class AnkiAutomataApp(ctk.CTk):
    def __init__(self):
        super().__init__()
            
        self.title("AnkiAutomata")
        self.geometry("1000x650")
        self.minsize(900, 500)
        
        self.current_scraped_data = None
        
        # --- Local IPC Server (The Bulletproof Shortcut Listener) ---
        self.search_triggered = False  # Thread-safe flag
        
        self.server_thread = threading.Thread(target=self.start_local_server, daemon=True)
        self.server_thread.start()
        
        # Start the continuous UI checking loop
        self.check_triggers()
            
        self.grid_columnconfigure(0, weight=4) 
        self.grid_columnconfigure(1, weight=6) 
        self.grid_rowconfigure(0, weight=1)
        
        # --- LEFT COLUMN (Inputs & Log) ---
        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=20)
        self.left_frame.grid_rowconfigure(2, weight=1) 
        
        self.header = ctk.CTkLabel(self.left_frame, text="AnkiAutomata ⚙️", font=ctk.CTkFont(size=24, weight="bold"))
        self.header.grid(row=0, column=0, pady=(0, 20), sticky="w")
        
        self.input_card = ctk.CTkFrame(self.left_frame, corner_radius=15)
        self.input_card.grid(row=1, column=0, sticky="ew")
        self.input_card.grid_columnconfigure(1, weight=1)
        
        label_font = ctk.CTkFont(size=13, weight="bold")
        
        ctk.CTkLabel(self.input_card, text="🗂️ Deck:", font=label_font, text_color=("gray30", "gray70")).grid(row=0, column=0, padx=15, pady=(20, 10), sticky="w")
        deck_inner = ctk.CTkFrame(self.input_card, fg_color="transparent")
        deck_inner.grid(row=0, column=1, padx=(0, 15), pady=(20, 10), sticky="ew")
        deck_inner.grid_columnconfigure(0, weight=1)
        
        self.deck_var = tk.StringVar(value=engine.config['anki']['default_deck'])
        self.deck_display = ctk.CTkEntry(deck_inner, textvariable=self.deck_var, state="readonly")
        self.deck_display.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        self.deck_btn = ctk.CTkButton(deck_inner, text="Change", width=60, command=self.change_deck, fg_color="transparent", border_width=1, text_color=("gray10", "gray90"))
        self.deck_btn.grid(row=0, column=1)
        
        ctk.CTkLabel(self.input_card, text="🎯 Word:", font=label_font, text_color=("gray30", "gray70")).grid(row=1, column=0, padx=15, pady=10, sticky="w")
        word_inner = ctk.CTkFrame(self.input_card, fg_color="transparent")
        word_inner.grid(row=1, column=1, padx=(0, 15), pady=10, sticky="ew")
        word_inner.grid_columnconfigure(0, weight=1)
        
        self.word_var = tk.StringVar()
        self.word_entry = ctk.CTkEntry(word_inner, textvariable=self.word_var, placeholder_text="Type to search...")
        self.word_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(word_inner, text="🔍", width=40, command=self.search_word).grid(row=0, column=1)
        
        ctk.CTkLabel(self.input_card, text="📖 Sentence:", font=label_font, text_color=("gray30", "gray70")).grid(row=2, column=0, padx=15, pady=(10, 20), sticky="nw")
        self.sentence_text = ctk.CTkTextbox(self.input_card, height=80, corner_radius=8)
        self.sentence_text.grid(row=2, column=1, padx=(0, 15), pady=(10, 20), sticky="ew")
        
        self.log_area = ctk.CTkTextbox(self.left_frame, height=90, font=ctk.CTkFont(family="Consolas", size=11), fg_color=("gray95", "gray10"))
        self.log_area.grid(row=3, column=0, sticky="esw", pady=(20, 0))
        self.log_area.insert("0.0", "System ready. Highlight text and press Ctrl+Alt+W.\n")
        self.log_area.configure(state="disabled")

        # --- RIGHT COLUMN (Editable Preview & Audio) ---
        self.right_frame = ctk.CTkFrame(self, corner_radius=15)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 20), pady=20)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(4, weight=1)
        
        self.word_header = ctk.CTkLabel(self.right_frame, text="Dictionary Editor", font=ctk.CTkFont(size=22, weight="bold"))
        self.word_header.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
        
        self.def_label = ctk.CTkLabel(self.right_frame, text="Meaning (Editable):", font=label_font, text_color=("gray30", "gray70"))
        self.def_label.grid(row=1, column=0, padx=20, pady=(5, 5), sticky="w")
        self.def_area = ctk.CTkTextbox(self.right_frame, font=ctk.CTkFont(size=16), fg_color=("gray95", "gray15"), wrap="word", height=80)
        self.def_area.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        
        self.ex_label = ctk.CTkLabel(self.right_frame, text="Examples (Editable):", font=label_font, text_color=("gray30", "gray70"))
        self.ex_label.grid(row=3, column=0, padx=20, pady=(5, 5), sticky="w")
        self.ex_area = ctk.CTkTextbox(self.right_frame, font=ctk.CTkFont(size=16), fg_color=("gray95", "gray15"), wrap="word")
        self.ex_area.grid(row=4, column=0, sticky="nsew", padx=20, pady=(0, 15))
        self.ex_area.bind('<Return>', self.auto_bullet)
        
        self.reset_editor()

        self.audio_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.audio_frame.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 15))
        self.audio_frame.grid_columnconfigure(0, weight=1)
        self.audio_frame.grid_columnconfigure(1, weight=1)
        
        self.uk_frame = ctk.CTkFrame(self.audio_frame, fg_color=("gray90", "gray20"))
        self.uk_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.uk_btn = ctk.CTkButton(self.uk_frame, text="▶ UK Play", width=80, state="disabled", command=lambda: self.play_audio("uk"))
        self.uk_btn.pack(side="left", padx=10, pady=10)
        self.uk_ipa_label = ctk.CTkLabel(self.uk_frame, text="-", font=ctk.CTkFont(size=14))
        self.uk_ipa_label.pack(side="left", padx=5, pady=10)
        
        self.us_frame = ctk.CTkFrame(self.audio_frame, fg_color=("gray90", "gray20"))
        self.us_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.us_btn = ctk.CTkButton(self.us_frame, text="▶ US Play", width=80, state="disabled", command=lambda: self.play_audio("us"))
        self.us_btn.pack(side="left", padx=10, pady=10)
        self.us_ipa_label = ctk.CTkLabel(self.us_frame, text="-", font=ctk.CTkFont(size=14))
        self.us_ipa_label.pack(side="left", padx=5, pady=10)

        self.submit_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.submit_frame.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 20))
        
        self.audio_choice = tk.StringVar(value="uk")
        ctk.CTkRadioButton(self.submit_frame, text="Save UK to Anki", variable=self.audio_choice, value="uk").pack(side="left", padx=(0, 15))
        ctk.CTkRadioButton(self.submit_frame, text="Save US to Anki", variable=self.audio_choice, value="us").pack(side="left")
        
        self.add_btn = ctk.CTkButton(self.submit_frame, text="➕ Confirm & Add to Anki", command=self.confirm_and_add, 
                                     height=45, font=ctk.CTkFont(size=14, weight="bold"), state="disabled")
        self.add_btn.pack(side="right", fill="x", expand=True, padx=(20, 0))
        
        self.word_entry.bind('<Return>', lambda event: self.search_word())
        self.word_entry.focus()

    def check_triggers(self):
        """Runs continuously in the main UI thread to safely check for background pings."""
        if self.search_triggered:
            self.search_triggered = False
            self.process_clipboard()
            
        self.after(200, self.check_triggers)

    def start_local_server(self):
        """Runs a tiny local server to listen for the OS shortcut curl command."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(('127.0.0.1', 24536))
            server.listen(1)
            while True:
                conn, addr = server.accept()
                conn.sendall(b"HTTP/1.1 200 OK\r\n\r\nSuccess")
                conn.close()
                # Safely tell the UI thread to run the search
                self.search_triggered = True
        except Exception as e:
            print(f"Local server error: {e}")

    def change_deck(self):
        available_decks = engine.get_anki_decks()
        current = self.deck_var.get()
        if current not in available_decks:
            available_decks.append(current)
            
        dialog = DeckSelectionDialog(self, available_decks, current)
        self.wait_window(dialog)
        
        if dialog.selected_deck:
            self.deck_var.set(dialog.selected_deck)

    def auto_bullet(self, event):
        self.ex_area.insert("insert", "\n• ")
        self.ex_area.see("insert")
        return "break" 

    def play_audio(self, region):
        if not self.current_scraped_data: return
        url = self.current_scraped_data.get(f"{region}_audio")
        headers = self.current_scraped_data.get("headers")
        if url:
            try:
                req = requests.get(url, headers=headers)
                audio_data = io.BytesIO(req.content)
                pygame.mixer.music.load(audio_data)
                pygame.mixer.music.play()
            except Exception as e:
                self.log(f"[!] Audio Playback Error: {e}")

    def log(self, message):
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")
        self.update()

    def reset_editor(self, message="Search a word to see its definition here..."):
        self.word_header.configure(text="Dictionary Editor")
        self.def_area.delete("0.0", tk.END)
        self.def_area.insert("0.0", message)
        self.ex_area.delete("0.0", tk.END)

    def populate_editor(self, data, word):
        self.word_header.configure(text=word.capitalize())
        self.def_area.delete("0.0", tk.END)
        self.def_area.insert("0.0", data['definition'])
        self.ex_area.delete("0.0", tk.END)
        
        if data['examples_raw']:
            examples_text = "\n".join([f"• {ex}" for ex in data['examples_raw']])
            self.ex_area.insert("0.0", examples_text)

    def reset_audio_ui(self):
        self.uk_btn.configure(state="disabled")
        self.us_btn.configure(state="disabled")
        self.uk_ipa_label.configure(text="-")
        self.us_ipa_label.configure(text="-")

    def process_clipboard(self):
        clipboard_text = pyperclip.paste().strip()
        if not clipboard_text: return
        
        # Bring window to front
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.attributes('-topmost', False)
        
        self.word_var.set(clipboard_text)
        self.search_word()

    def search_word(self, manual_url=None):
        deck = self.deck_var.get().strip()
        word = self.word_var.get().strip()
        
        if not word: return
            
        self.add_btn.configure(state="disabled")
        self.reset_audio_ui()
        self.current_scraped_data = None
        self.reset_editor("Searching Cambridge Dictionary...")
        self.log(f"Searching '{word}'...")
        self.update()
        
        try:
            if engine.is_duplicate(word, deck):
                self.log(f"[!] Warning: '{word}' exists in '{deck}'.")
                self.reset_editor(f"⚠️ '{word}' is already in your Anki deck!")
                return
        except Exception as e:
            self.log(f"[!] Anki Error: {e}")
            self.reset_editor("⚠️ Ensure Anki is open and AnkiConnect is installed.")
            return

        data = engine.scrape_cambridge(word, manual_url)
        
        if not data and not manual_url:
            dialog = ctk.CTkInputDialog(text=f"Could not find '{word}'.\nPaste direct Cambridge URL:", title="Manual Entry")
            url_input = dialog.get_input()
            if url_input: self.search_word(manual_url=url_input.strip())
            else: self.reset_editor("Search canceled.")
            return
            
        if not data:
            self.log(f"[!] Skipped '{word}'. No data found.")
            self.reset_editor("No definition found.")
            return
            
        self.current_scraped_data = data
        
        if data['uk_audio']:
            self.uk_btn.configure(state="normal")
            self.uk_ipa_label.configure(text=data['uk_ipa'])
        if data['us_audio']:
            self.us_btn.configure(state="normal")
            self.us_ipa_label.configure(text=data['us_ipa'])
            if not data['uk_audio']: self.audio_choice.set("us")
        
        self.populate_editor(data, word)
        self.add_btn.configure(state="normal")
        self.log("Definition found. Edit if needed, then Confirm.")

    def confirm_and_add(self):
        if not self.current_scraped_data: return
            
        deck = self.deck_var.get().strip()
        data = self.current_scraped_data
        word = data['word']
        sentence = self.sentence_text.get("1.0", tk.END).strip()
        region = self.audio_choice.get()
        
        target_audio_url = data.get(f"{region}_audio")
        target_ipa = data.get(f"{region}_ipa")
        
        edited_definition = self.def_area.get("1.0", tk.END).strip()
        edited_examples = self.ex_area.get("1.0", tk.END).strip()
        separator = engine.config['templates']['example_separator']
        edited_examples_html = edited_examples.replace('\n', separator)
        
        self.log("Building Anki note...")
        self.update()
        
        audio_filename = f"ankiautomata_{region}_{word.replace(' ', '_')}.mp3"
        audio_tag = ""
        if target_audio_url:
            try:
                audio_req = requests.get(target_audio_url, headers=data['headers'])
                audio_base64 = base64.b64encode(audio_req.content).decode('utf-8')
                engine.invoke_anki('storeMediaFile', filename=audio_filename, data=audio_base64)
                audio_tag = f"[sound:{audio_filename}]"
            except Exception as e:
                self.log(f"[!] Audio save error: {e}")
        
        bolded_definition = engine.bold_word(word, edited_definition)
        bolded_examples = engine.bold_word(word, edited_examples_html)
        
        front_html = engine.config['templates']['front'].format(word=word)
        highlighted_sentence = engine.format_sentence(word, sentence)
        back_html = engine.config['templates']['back_layout'].format(
            definition=bolded_definition, 
            examples=bolded_examples
        )
        
        note = {
            "deckName": deck,
            "modelName": engine.config['anki']['model_name'],
            "fields": {
                "Front": front_html,
                "Example sentence": highlighted_sentence,
                "Pronounciation": f"{target_ipa} {audio_tag}",
                "Back": back_html
            },
            "options": {"allowDuplicate": False},
            "tags": engine.config['anki']['tags']
        }
        
        try:
            engine.invoke_anki('addNote', note=note)
            self.log(f"[+] SUCCESS! Added '{word}' ({region.upper()}).")
            
            self.word_var.set("")
            self.sentence_text.delete("1.0", tk.END)
            self.reset_editor("Ready for next word...")
            self.add_btn.configure(state="disabled")
            self.reset_audio_ui()
            self.current_scraped_data = None
            self.word_entry.focus()
            
        except Exception as e:
            self.log(f"[!] Failed to add note: {e}")

if __name__ == "__main__":
    app = AnkiAutomataApp()
    app.mainloop()