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
    def __init__(self, parent, decks, current_deck, font=None):
        super().__init__(parent)
        self.title("Select Anki Deck")
        self.geometry("420x520")
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
                        fieldbackground=bg_color, borderwidth=0, rowheight=26)
        style.map('Treeview', background=[('selected', sel_bg)])

        self.tree = ttk.Treeview(self, show="tree", selectmode="browse")
        self.tree.pack(expand=True, fill="both", padx=15, pady=(15, 5))
        
        self.populate_tree(decks)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkButton(btn_frame, text="Select", command=self.confirm, font=font).pack(side="right", padx=(10, 0))
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy, fg_color="transparent", border_width=1, font=font).pack(side="right")

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
        self.geometry("1040x700")
        self.minsize(940, 580)
        
        self.current_scraped_data = None
        
        self._setup_fonts()
        
        # Local IPC Server for shortcuts
        self.search_triggered = False
        self.server_thread = threading.Thread(target=self.start_local_server, daemon=True)
        self.server_thread.start()
        self.check_triggers()
            
        self.grid_columnconfigure(0, weight=4) 
        self.grid_columnconfigure(1, weight=6) 
        self.grid_rowconfigure(0, weight=1)
        
        # --- LEFT COLUMN (Inputs & Log) ---
        self.left_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.left_frame.grid(row=0, column=0, sticky="nsew", padx=(20, 10), pady=20)
        self.left_frame.grid_rowconfigure(2, weight=1) 
        
        # Header Row with App Title and Text Scale Dropdown
        self.header_frame = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, pady=(0, 15), sticky="ew")
        
        self.header = ctk.CTkLabel(self.header_frame, text="AnkiAutomata ⚙️", font=self.fonts["title"])
        self.header.pack(side="left")
        
        scale_container = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        scale_container.pack(side="right")
        
        ctk.CTkLabel(scale_container, text="Text Size:", font=self.fonts["small"], text_color=("gray40", "gray70")).pack(side="left", padx=(0, 6))
        self.scale_menu = ctk.CTkOptionMenu(
            scale_container,
            values=list(self.font_scale_factors.keys()),
            command=self.on_font_scale_changed,
            font=self.fonts["small"],
            width=125,
            height=28
        )
        self.scale_menu.set(self.current_scale_choice)
        self.scale_menu.pack(side="left")
        
        self.input_card = ctk.CTkFrame(self.left_frame, corner_radius=15)
        self.input_card.grid(row=1, column=0, sticky="ew")
        self.input_card.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(self.input_card, text="🗂️ Deck:", font=self.fonts["label"], text_color=("gray30", "gray70")).grid(row=0, column=0, padx=15, pady=(20, 10), sticky="w")
        deck_inner = ctk.CTkFrame(self.input_card, fg_color="transparent")
        deck_inner.grid(row=0, column=1, padx=(0, 15), pady=(20, 10), sticky="ew")
        deck_inner.grid_columnconfigure(0, weight=1)
        
        saved_deck = engine.get_preference('selected_deck', engine.config['anki']['default_deck'])
        self.deck_var = tk.StringVar(value=saved_deck)
        self.deck_display = ctk.CTkEntry(deck_inner, textvariable=self.deck_var, font=self.fonts["body"], state="readonly")
        self.deck_display.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        self.deck_btn = ctk.CTkButton(deck_inner, text="Change", width=60, command=self.change_deck, font=self.fonts["btn"], fg_color="transparent", border_width=1, text_color=("gray10", "gray90"))
        self.deck_btn.grid(row=0, column=1)
        
        ctk.CTkLabel(self.input_card, text="🎯 Word:", font=self.fonts["label"], text_color=("gray30", "gray70")).grid(row=1, column=0, padx=15, pady=10, sticky="w")
        word_inner = ctk.CTkFrame(self.input_card, fg_color="transparent")
        word_inner.grid(row=1, column=1, padx=(0, 15), pady=10, sticky="ew")
        word_inner.grid_columnconfigure(0, weight=1)
        
        self.word_var = tk.StringVar()
        self.word_entry = ctk.CTkEntry(word_inner, textvariable=self.word_var, font=self.fonts["body"], placeholder_text="Type to search...")
        self.word_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(word_inner, text="🔍", width=40, font=self.fonts["btn"], command=self.search_word).grid(row=0, column=1)
        
        ctk.CTkLabel(self.input_card, text="📖 Sentence:", font=self.fonts["label"], text_color=("gray30", "gray70")).grid(row=2, column=0, padx=15, pady=(10, 20), sticky="nw")
        self.sentence_text = ctk.CTkTextbox(self.input_card, height=80, corner_radius=8, font=self.fonts["body"])
        self.sentence_text.grid(row=2, column=1, padx=(0, 15), pady=(10, 20), sticky="ew")
        
        self.log_area = ctk.CTkTextbox(self.left_frame, height=90, font=self.fonts["log"], fg_color=("gray95", "gray10"))
        self.log_area.grid(row=3, column=0, sticky="esw", pady=(20, 0))
        self.log_area.insert("0.0", "System ready. Highlight text and press Ctrl+Alt+W.\n")
        self.log_area.configure(state="disabled")

        # --- RIGHT COLUMN (Editable Preview & Audio) ---
        self.right_frame = ctk.CTkFrame(self, corner_radius=15)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 20), pady=20)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(5, weight=1)
        
        self.word_header = ctk.CTkLabel(self.right_frame, text="Dictionary Editor", font=self.fonts["section"])
        self.word_header.grid(row=0, column=0, padx=20, pady=(15, 5), sticky="w")
        
        # Meaning Selector and "Auto-combine All Meanings" Switch
        self.sense_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.sense_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 5))
        
        ctk.CTkLabel(self.sense_frame, text="Meaning:", font=self.fonts["label"], text_color=("gray30", "gray70")).pack(side="left", padx=(0, 8))
        
        self.sense_var = tk.StringVar(value="Select meaning...")
        self.sense_menu = ctk.CTkOptionMenu(self.sense_frame, variable=self.sense_var, values=["Select meaning..."], 
                                            command=self.on_sense_changed, font=self.fonts["small"], state="disabled")
        self.sense_menu.pack(side="left", fill="x", expand=True, padx=(0, 12))

        saved_auto_all = engine.get_preference('auto_all_meanings', False)
        self.auto_all_meanings_var = tk.BooleanVar(value=saved_auto_all)
        self.auto_all_switch = ctk.CTkSwitch(
            self.sense_frame,
            text="Auto-combine All",
            variable=self.auto_all_meanings_var,
            command=self.on_toggle_auto_all,
            font=self.fonts["small"]
        )
        self.auto_all_switch.pack(side="right")

        self.def_label = ctk.CTkLabel(self.right_frame, text="Definition (Editable):", font=self.fonts["label"], text_color=("gray30", "gray70"))
        self.def_label.grid(row=2, column=0, padx=20, pady=(5, 5), sticky="w")
        self.def_area = ctk.CTkTextbox(self.right_frame, font=self.fonts["editor"], fg_color=("gray95", "gray15"), wrap="word", height=75)
        self.def_area.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 10))
        
        # Examples Toolbar
        self.ex_header_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.ex_header_frame.grid(row=4, column=0, padx=20, pady=(5, 5), sticky="ew")
        
        self.ex_label = ctk.CTkLabel(self.ex_header_frame, text="Examples (Editable):", font=self.fonts["label"], text_color=("gray30", "gray70"))
        self.ex_label.pack(side="left")
        
        self.all_ex_btn = ctk.CTkButton(self.ex_header_frame, text="Show All Examples", width=125, height=24, 
                                        font=self.fonts["small"], fg_color="transparent", border_width=1, 
                                        command=self.load_all_examples, state="disabled")
        self.all_ex_btn.pack(side="right")
        
        self.ex_area = ctk.CTkTextbox(self.right_frame, font=self.fonts["editor"], fg_color=("gray95", "gray15"), wrap="word")
        self.ex_area.grid(row=5, column=0, sticky="nsew", padx=20, pady=(0, 15))
        self.ex_area.bind('<Return>', self.auto_bullet)
        
        self.reset_editor()

        self.audio_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.audio_frame.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 15))
        self.audio_frame.grid_columnconfigure(0, weight=1)
        self.audio_frame.grid_columnconfigure(1, weight=1)
        
        self.uk_frame = ctk.CTkFrame(self.audio_frame, fg_color=("gray90", "gray20"))
        self.uk_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.uk_btn = ctk.CTkButton(self.uk_frame, text="▶ UK Play", width=80, font=self.fonts["btn"], state="disabled", command=lambda: self.play_audio("uk"))
        self.uk_btn.pack(side="left", padx=10, pady=10)
        self.uk_ipa_label = ctk.CTkLabel(self.uk_frame, text="-", font=self.fonts["body"])
        self.uk_ipa_label.pack(side="left", padx=5, pady=10)
        
        self.us_frame = ctk.CTkFrame(self.audio_frame, fg_color=("gray90", "gray20"))
        self.us_frame.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.us_btn = ctk.CTkButton(self.us_frame, text="▶ US Play", width=80, font=self.fonts["btn"], state="disabled", command=lambda: self.play_audio("us"))
        self.us_btn.pack(side="left", padx=10, pady=10)
        self.us_ipa_label = ctk.CTkLabel(self.us_frame, text="-", font=self.fonts["body"])
        self.us_ipa_label.pack(side="left", padx=5, pady=10)

        self.submit_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.submit_frame.grid(row=7, column=0, sticky="ew", padx=20, pady=(0, 20))
        
        saved_audio = engine.get_preference('audio_choice', 'uk')
        self.audio_choice = tk.StringVar(value=saved_audio)
        ctk.CTkRadioButton(self.submit_frame, text="Save UK to Anki", variable=self.audio_choice, 
                           value="uk", font=self.fonts["body"], command=self.on_audio_choice_changed).pack(side="left", padx=(0, 15))
        ctk.CTkRadioButton(self.submit_frame, text="Save US to Anki", variable=self.audio_choice, 
                           value="us", font=self.fonts["body"], command=self.on_audio_choice_changed).pack(side="left")
        
        self.add_btn = ctk.CTkButton(self.submit_frame, text="➕ Confirm & Add to Anki", command=self.confirm_and_add, 
                                     height=45, font=self.fonts["btn_large"], state="disabled")
        self.add_btn.pack(side="right", fill="x", expand=True, padx=(20, 0))
        
        self.word_entry.bind('<Return>', lambda event: self.search_word())
        self.word_entry.focus()

    def _setup_fonts(self):
        self.base_font_sizes = {
            "title": 23,
            "section": 20,
            "label": 13,
            "body": 13,
            "editor": 15,
            "btn": 13,
            "btn_large": 14,
            "log": 11,
            "small": 11,
        }

        self.font_scale_factors = {
            "Normal (100%)": 1.0,
            "Medium (115%)": 1.15,
            "Large (130%)": 1.30,
            "XL (145%)": 1.45,
        }

        saved_scale = engine.get_preference('font_scale', 'Normal (100%)')
        self.current_scale_choice = saved_scale if saved_scale in self.font_scale_factors else "Normal (100%)"
        scale = self.font_scale_factors[self.current_scale_choice]

        self.fonts = {
            "title": ctk.CTkFont(size=int(round(self.base_font_sizes["title"] * scale)), weight="bold"),
            "section": ctk.CTkFont(size=int(round(self.base_font_sizes["section"] * scale)), weight="bold"),
            "label": ctk.CTkFont(size=int(round(self.base_font_sizes["label"] * scale)), weight="bold"),
            "body": ctk.CTkFont(size=int(round(self.base_font_sizes["body"] * scale))),
            "editor": ctk.CTkFont(size=int(round(self.base_font_sizes["editor"] * scale))),
            "btn": ctk.CTkFont(size=int(round(self.base_font_sizes["btn"] * scale)), weight="bold"),
            "btn_large": ctk.CTkFont(size=int(round(self.base_font_sizes["btn_large"] * scale)), weight="bold"),
            "log": ctk.CTkFont(family="Consolas", size=int(round(self.base_font_sizes["log"] * scale))),
            "small": ctk.CTkFont(size=int(round(self.base_font_sizes["small"] * scale))),
        }

    def on_font_scale_changed(self, choice: str):
        self.current_scale_choice = choice
        scale = self.font_scale_factors.get(choice, 1.0)
        for name, base_sz in self.base_font_sizes.items():
            new_sz = max(9, int(round(base_sz * scale)))
            self.fonts[name].configure(size=new_sz)

        # Explicit configuration update for multiline text boxes to trigger redraw
        if hasattr(self, 'def_area'):
            self.def_area.configure(font=self.fonts["editor"])
            self.ex_area.configure(font=self.fonts["editor"])
            self.sentence_text.configure(font=self.fonts["body"])
            self.log_area.configure(font=self.fonts["log"])

        engine.save_preference('font_scale', choice)

    def on_toggle_auto_all(self):
        val = self.auto_all_meanings_var.get()
        engine.save_preference('auto_all_meanings', val)
        if not self.current_scraped_data:
            return
        
        senses = self.current_scraped_data.get('senses', [])
        if len(senses) > 1:
            if val:
                self.sense_var.set("📚 All Meanings & Examples")
                self.apply_sense("all")
            else:
                first_label = self.format_sense_label(0, senses[0])
                self.sense_var.set(first_label)
                self.apply_sense(0)

    def on_audio_choice_changed(self):
        engine.save_preference('audio_choice', self.audio_choice.get())

    def check_triggers(self):
        if self.search_triggered:
            self.search_triggered = False
            self.process_clipboard()
        self.after(200, self.check_triggers)

    def start_local_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(('127.0.0.1', 24536))
            server.listen(1)
            while True:
                conn, addr = server.accept()
                conn.sendall(b"HTTP/1.1 200 OK\r\n\r\nSuccess")
                conn.close()
                self.search_triggered = True
        except Exception as e:
            print(f"Local server error: {e}")

    def change_deck(self):
        available_decks = engine.get_anki_decks()
        current = self.deck_var.get()
        if current not in available_decks:
            available_decks.append(current)
            
        dialog = DeckSelectionDialog(self, available_decks, current, font=self.fonts["btn"])
        self.wait_window(dialog)
        
        if dialog.selected_deck:
            self.deck_var.set(dialog.selected_deck)
            engine.save_preference('selected_deck', dialog.selected_deck)

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
        self.sense_menu.configure(values=["Select meaning..."], state="disabled")
        self.sense_var.set("Select meaning...")
        self.all_ex_btn.configure(state="disabled")

    def format_sense_label(self, idx, sense):
        tags = []
        if sense.get('pos'):
            tags.append(sense['pos'])
        if sense.get('guideword'):
            gw = sense['guideword'].strip('() ')
            tags.append(gw)
        tag_str = f"[{', '.join(tags)}] " if tags else ""
        
        defn = sense.get('definition', '')
        preview = defn[:45] + ("..." if len(defn) > 45 else "")
        return f"{idx + 1}. {tag_str}{preview}"

    def populate_editor(self, data, word):
        self.word_header.configure(text=word.capitalize())
        senses = data.get('senses', [])
        
        if not senses:
            self.def_area.delete("0.0", tk.END)
            self.def_area.insert("0.0", data.get('definition', 'No definition found.'))
            self.ex_area.delete("0.0", tk.END)
            if data.get('examples_raw'):
                self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in data['examples_raw']]))
            self.sense_menu.configure(values=["Default Definition"], state="disabled")
            self.sense_var.set("Default Definition")
            self.all_ex_btn.configure(state="normal")
            return

        menu_items = []
        for i, s in enumerate(senses):
            menu_items.append(self.format_sense_label(i, s))
            
        if len(senses) > 1:
            menu_items.append("📚 All Meanings & Examples")

        self.sense_menu.configure(values=menu_items, state="normal")
        self.all_ex_btn.configure(state="normal")
        
        # Respect user preference: Auto-combine vs First Meaning
        if self.auto_all_meanings_var.get() and len(senses) > 1:
            self.sense_var.set("📚 All Meanings & Examples")
            self.apply_sense("all")
        else:
            self.sense_var.set(menu_items[0])
            self.apply_sense(0)

    def apply_sense(self, sense_choice):
        if not self.current_scraped_data: return
        senses = self.current_scraped_data.get('senses', [])
        
        if sense_choice == "all":
            def_lines = []
            for i, s in enumerate(senses):
                tag = f"[{s['pos']}] " if s.get('pos') else ""
                gw = f"({s['guideword'].strip('() ')}) " if s.get('guideword') else ""
                def_lines.append(f"{i + 1}. {tag}{gw}{s['definition']}")
            
            self.def_area.delete("0.0", tk.END)
            self.def_area.insert("0.0", "\n\n".join(def_lines))
            
            all_ex = self.current_scraped_data.get('examples_raw', [])
            self.ex_area.delete("0.0", tk.END)
            if all_ex:
                self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in all_ex]))
        else:
            idx = int(sense_choice)
            if 0 <= idx < len(senses):
                s = senses[idx]
                self.def_area.delete("0.0", tk.END)
                self.def_area.insert("0.0", s['definition'])
                
                ex_list = s.get('examples', [])
                if not ex_list:
                    ex_list = self.current_scraped_data.get('examples_raw', [])
                    
                self.ex_area.delete("0.0", tk.END)
                if ex_list:
                    self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in ex_list]))

    def on_sense_changed(self, choice):
        if choice == "📚 All Meanings & Examples":
            self.apply_sense("all")
        else:
            try:
                idx = int(choice.split(".")[0]) - 1
                self.apply_sense(idx)
            except Exception:
                self.apply_sense(0)

    def load_all_examples(self):
        if not self.current_scraped_data: return
        all_ex = self.current_scraped_data.get('examples_raw', [])
        if all_ex:
            self.ex_area.delete("0.0", tk.END)
            self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in all_ex]))

    def reset_audio_ui(self):
        self.uk_btn.configure(state="disabled")
        self.us_btn.configure(state="disabled")
        self.uk_ipa_label.configure(text="-")
        self.us_ipa_label.configure(text="-")

    def process_clipboard(self):
        clipboard_text = pyperclip.paste().strip()
        if not clipboard_text: return
        
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
        count = len(data.get('senses', []))
        self.log(f"Found {count} meaning{'s' if count != 1 else ''}. Select meaning, edit if needed, then Confirm.")

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