import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
from html import escape
import requests
import base64
import pyperclip
import io
import pygame
import argparse
from pathlib import Path
from queue import Empty, Queue
import threading
import re
import engine
from ipc import LookupServer

ctk.set_default_color_theme(str(Path(__file__).with_name('theme.json')))
ctk.set_appearance_mode(engine.get_preference('appearance', 'System'))

SURFACE = ('#FFFFFF', '#1C2825')
FIELD = ('#F8FAF6', '#17221F')
MUTED = ('#647874', '#98ABA5')
BORDER = ('#DCE4DC', '#344740')
ACCENT = ('#276B5B', '#70B69E')
TEXT = ('#243B3A', '#E5EEEB')

class DeckSelectionDialog(ctk.CTkToplevel):
    def __init__(self, parent, decks, current_deck, font=None):
        super().__init__(parent)
        self.title("Select Anki Deck")
        self.geometry("420x520")
        self.selected_deck = current_deck
        
        self.transient(parent)
        self.grab_set()
        
        self.bind("<Control-w>", lambda e: self.destroy())
        self.bind("<Control-W>", lambda e: self.destroy())
        self.bind("<Escape>", lambda e: self.destroy())
        
        style = ttk.Style(self)
        mode = ctk.get_appearance_mode()
        
        if mode == "Dark":
            bg_color = SURFACE[1]
            text_color = TEXT[1]
            sel_bg = "#35735F"
        else:
            bg_color = SURFACE[0]
            text_color = TEXT[0]
            sel_bg = "#276B5B"
            
        style.theme_use("default")
        style.configure("Treeview", background=bg_color, foreground=text_color, 
                        fieldbackground=bg_color, borderwidth=0, rowheight=26)
        style.map('Treeview', background=[('selected', sel_bg)], foreground=[('selected', 'white')])

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
    def __init__(self, initial_word=None):
        super().__init__()
            
        self.title("AnkiAutomata")
        
        saved_w = engine.get_preference('window_width', 1040)
        saved_h = engine.get_preference('window_height', 820)
        try:
            self.geometry(f"{saved_w}x{saved_h}")
        except Exception:
            self.geometry("1040x820")
            
        self.minsize(840, 720)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.bind_all("<Control-w>", self.on_closing)
        self.bind_all("<Control-W>", self.on_closing)
        try:
            self.bind_all("<Command-w>", self.on_closing)
            self.bind_all("<Command-W>", self.on_closing)
        except Exception:
            pass
        
        self.current_scraped_data = None
        self._is_dragging_splitter = False
        
        self.user_pref_def_height = engine.get_preference('user_def_height', 120)
        
        self._setup_fonts()
        
        self.lookup_requests = Queue(maxsize=10)
        self.lookup_server = None
            
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._log_visible = False

        self.topbar = ctk.CTkFrame(self, fg_color="transparent")
        self.topbar.grid(row=0, column=0, sticky="ew", padx=28, pady=(22, 16))
        self.topbar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.topbar, text="a", width=36, height=36, corner_radius=10,
                     fg_color=('#276B5B', '#438D78'), text_color='white',
                     font=self.fonts['title']).grid(row=0, column=0, padx=(0, 12))
        ctk.CTkLabel(self.topbar, text="AnkiAutomata", font=self.fonts['title'],
                     anchor='w').grid(row=0, column=1, sticky='w')
        self.deck_var = tk.StringVar(value=engine.get_preference(
            'selected_deck', engine.config['anki']['default_deck']))
        self.deck_display = ctk.CTkEntry(self.topbar, textvariable=self.deck_var,
                                       width=220, state='readonly', font=self.fonts['small'])
        self.deck_display.grid(row=0, column=2, padx=(12, 6))
        self.deck_btn = self.quiet_button(self.topbar, 'Change deck', self.change_deck, width=105)
        self.deck_btn.grid(row=0, column=3, padx=(0, 8))
        self.settings_btn = self.quiet_button(self.topbar, 'Settings', self.open_settings, width=80)
        self.settings_btn.grid(row=0, column=4)

        self.search_bar = ctk.CTkFrame(self, fg_color='transparent')
        self.search_bar.grid(row=1, column=0, sticky='ew', padx=28, pady=(0, 18))
        self.search_bar.grid_columnconfigure(0, weight=1)
        self.word_var = tk.StringVar()
        self.word_entry = ctk.CTkEntry(self.search_bar, textvariable=self.word_var,
            placeholder_text='Look up a word or phrase', height=46, font=self.fonts['body'])
        self.word_entry.grid(row=0, column=0, sticky='ew', padx=(0, 10))
        self.search_btn = ctk.CTkButton(self.search_bar, text='Search', width=110,
                                       height=46, font=self.fonts['btn'], command=self.search_word)
        self.search_btn.grid(row=0, column=1)

        self.right_frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=16,
                                        border_width=1, border_color=BORDER)
        self.right_frame.grid(row=2, column=0, sticky='nsew', padx=28)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(7, weight=1)
        self.word_header = ctk.CTkLabel(self.right_frame, text='A word worth remembering.',
                                        font=self.fonts['word'], anchor='w')
        self.word_header.grid(row=0, column=0, sticky='ew', padx=24, pady=(18, 0))
        self.word_meta = ctk.CTkLabel(self.right_frame, text='CAMBRIDGE DICTIONARY',
                                     text_color=MUTED, font=self.fonts['small'], anchor='w')
        self.word_meta.grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 8))

        self.audio_frame = ctk.CTkFrame(self.right_frame, fg_color='transparent')
        self.audio_frame.grid(row=2, column=0, sticky='ew', padx=24, pady=(0, 14))
        self.uk_btn = self.quiet_button(self.audio_frame, 'Play UK', lambda: self.play_audio('uk'), width=78)
        self.uk_btn.pack(side='left')
        self.uk_ipa_label = ctk.CTkLabel(self.audio_frame, text='—', font=self.fonts['body'], text_color=MUTED)
        self.uk_ipa_label.pack(side='left', padx=(8, 24))
        self.us_btn = self.quiet_button(self.audio_frame, 'Play US', lambda: self.play_audio('us'), width=78)
        self.us_btn.pack(side='left')
        self.us_ipa_label = ctk.CTkLabel(self.audio_frame, text='—', font=self.fonts['body'], text_color=MUTED)
        self.us_ipa_label.pack(side='left', padx=8)
        self.reset_audio_ui()

        self.sense_frame = ctk.CTkFrame(self.right_frame, fg_color='transparent')
        self.sense_frame.grid(row=3, column=0, sticky='ew', padx=24, pady=(0, 14))
        ctk.CTkLabel(self.sense_frame, text='MEANING', text_color=MUTED,
                     font=self.fonts['label']).pack(side='left', padx=(0, 14))
        self.sense_var = tk.StringVar(value='Select meaning...')
        self.sense_menu = ctk.CTkOptionMenu(self.sense_frame, variable=self.sense_var,
            values=['Select meaning...'], command=self.on_sense_changed,
            font=self.fonts['body'], dynamic_resizing=False, state='disabled', height=34)
        self.sense_menu.pack(side='left', fill='x', expand=True)
        self.auto_all_meanings_var = tk.BooleanVar(value=engine.get_preference('auto_all_meanings', False))

        self.def_label = ctk.CTkLabel(self.right_frame, text='DEFINITION',
                                     text_color=MUTED, font=self.fonts['label'], anchor='w')
        self.def_label.grid(row=4, column=0, sticky='ew', padx=24, pady=(0, 6))
        self.def_area = ctk.CTkTextbox(self.right_frame, font=self.fonts['editor'],
            wrap='word', height=self.user_pref_def_height, fg_color=FIELD)
        self.def_area.grid(row=5, column=0, sticky='ew', padx=24)
        self.splitter = ctk.CTkFrame(self.right_frame, height=7, corner_radius=3,
                                     fg_color=BORDER, cursor='sb_v_double_arrow')
        self.splitter.grid(row=6, column=0, sticky='ew', padx=24, pady=8)
        self.grip_indicator = ctk.CTkFrame(self.splitter, width=32, height=3,
            fg_color=MUTED, corner_radius=2, cursor='sb_v_double_arrow')
        self.grip_indicator.place(relx=0.5, rely=0.5, anchor='center')
        for widget in (self.splitter, self.grip_indicator):
            widget.bind('<Button-1>', self._on_splitter_press)
            widget.bind('<B1-Motion>', self._on_splitter_drag)
            widget.bind('<ButtonRelease-1>', self._on_splitter_release)

        self.examples_frame = ctk.CTkFrame(self.right_frame, fg_color='transparent')
        self.examples_frame.grid(row=7, column=0, sticky='nsew', padx=24)
        self.examples_frame.grid_columnconfigure(0, weight=1)
        self.examples_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self.examples_frame, text='EXAMPLES', text_color=MUTED,
                     font=self.fonts['label']).grid(row=0, column=0, sticky='w', pady=(0, 6))
        self.all_ex_btn = self.quiet_button(self.examples_frame, 'Show all', self.load_all_examples, width=80)
        self.all_ex_btn.grid(row=0, column=1, sticky='e', pady=(0, 6))
        self.all_ex_btn.configure(state='disabled')
        self.ex_area = ctk.CTkTextbox(self.examples_frame, height=130, fg_color=FIELD,
                                     wrap='word', font=self.fonts['editor'])
        self.ex_area.grid(row=1, column=0, columnspan=2, sticky='nsew')
        self.ex_area.bind('<Return>', self.auto_bullet)

        self.context_frame = ctk.CTkFrame(self.right_frame, fg_color='transparent')
        self.context_frame.grid(row=8, column=0, sticky='ew', padx=24, pady=(14, 20))
        ctk.CTkLabel(self.context_frame, text='YOUR SENTENCE', text_color=MUTED,
                     font=self.fonts['label']).pack(anchor='w', pady=(0, 6))
        self.sentence_text = ctk.CTkTextbox(self.context_frame, height=64, fg_color=FIELD,
                                           wrap='word', font=self.fonts['body'])
        self.sentence_text.pack(fill='x')
        self.reset_editor()

        self.submit_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.submit_frame.grid(row=3, column=0, sticky='ew', padx=28, pady=(16, 10))
        self.submit_frame.grid_columnconfigure(0, weight=1)
        self.audio_choice = tk.StringVar(value=engine.get_preference('audio_choice', 'uk'))
        self.audio_save_frame = ctk.CTkFrame(self.submit_frame, fg_color='transparent')
        self.audio_save_frame.grid(row=0, column=0, sticky='w')
        ctk.CTkLabel(self.audio_save_frame, text='Save pronunciation', font=self.fonts['small'],
                     text_color=MUTED).pack(side='left', padx=(0, 16))
        for region in ('uk', 'us'):
            ctk.CTkRadioButton(self.audio_save_frame, text=region.upper(), variable=self.audio_choice,
                value=region, font=self.fonts['body'], width=62, radiobutton_width=18,
                radiobutton_height=18, command=self.on_audio_choice_changed).pack(side='left', padx=(0, 8))
        self.add_btn = ctk.CTkButton(self.submit_frame, text='Add to Anki', width=180,
            height=44, font=self.fonts['btn_large'], state='disabled', command=self.confirm_and_add)
        self.add_btn.grid(row=0, column=1, sticky='e')

        self.status_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.status_frame.grid(row=4, column=0, sticky='ew', padx=28, pady=(0, 12))
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.status_frame, text='Ready · Select text in your PDF to begin',
            font=self.fonts['small'], text_color=MUTED, anchor='w')
        self.status_label.grid(row=0, column=0, sticky='ew')
        self.activity_btn = self.quiet_button(self.status_frame, 'Activity', self.toggle_activity, width=70)
        self.activity_btn.grid(row=0, column=1)
        self.log_area = ctk.CTkTextbox(self, height=100, font=self.fonts['log'], state='disabled')

        self.word_entry.bind('<Return>', lambda event: self.search_word())
        self.word_entry.focus()
        self.server_thread = threading.Thread(target=self.start_local_server, daemon=True)
        self.server_thread.start()
        if initial_word:
            self.lookup_requests.put_nowait(initial_word)
        self.after(200, self.check_triggers)

    def quiet_button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, font=self.fonts['small'],
            height=32, fg_color='transparent', hover_color=BORDER, text_color=TEXT, **kwargs)

    def toggle_activity(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_area.grid(row=5, column=0, sticky='ew', padx=28, pady=(0, 16))
        else:
            self.log_area.grid_remove()

    def open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title('Settings')
        dialog.geometry('420x340')
        dialog.transient(self)
        dialog.grab_set()
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        ctk.CTkLabel(dialog, text='Make it yours', font=self.fonts['title']).pack(anchor='w', padx=24, pady=(24, 18))
        ctk.CTkLabel(dialog, text='Appearance', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24)
        appearance = ctk.CTkOptionMenu(dialog, values=['System', 'Light', 'Dark'], command=self.on_appearance_changed)
        appearance.set(engine.get_preference('appearance', 'System'))
        appearance.pack(fill='x', padx=24, pady=(6, 14))
        ctk.CTkLabel(dialog, text='Text size', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24)
        scale = ctk.CTkOptionMenu(dialog, values=list(self.font_scale_factors), command=self.on_font_scale_changed)
        scale.set(self.current_scale_choice)
        scale.pack(fill='x', padx=24, pady=(6, 18))
        ctk.CTkSwitch(dialog, text='Combine all meanings by default', variable=self.auto_all_meanings_var,
                       command=self.on_toggle_auto_all, font=self.fonts['small']).pack(anchor='w', padx=24)

    def on_appearance_changed(self, choice):
        ctk.set_appearance_mode(choice)
        engine.save_preference('appearance', choice)

    # --- Height Splitter Logic ---
    def _on_splitter_hover(self, entering):
        if not self._is_dragging_splitter:
            color = ('#276B5B', '#438D78') if entering else BORDER
            grip_color = ("#ffffff", "#dce4ee") if entering else ("gray55", "gray50")
            self.splitter.configure(fg_color=color)
            self.grip_indicator.configure(fg_color=grip_color)

    def _on_splitter_press(self, event):
        self._is_dragging_splitter = True
        self._drag_start_y = event.y_root
        h = self.def_area.winfo_height()
        self._drag_start_h = h if h > 1 else self.def_area.cget("height")
        self.splitter.configure(fg_color=('#276B5B', '#438D78'))

    def _on_splitter_drag(self, event):
        if not self._is_dragging_splitter: return
        delta = event.y_root - self._drag_start_y
        new_h = self._drag_start_h + delta
        
        min_h = 55
        rf_h = self.right_frame.winfo_height()
        max_h = max(min_h + 40, rf_h - 260) if rf_h > 350 else 400
        
        clamped_h = max(min_h, min(new_h, max_h))
        self.def_area.configure(height=clamped_h)
        self.user_pref_def_height = clamped_h

    def _on_splitter_release(self, event):
        self._is_dragging_splitter = False
        self.splitter.configure(fg_color=BORDER)
        self.grip_indicator.configure(fg_color=("gray55", "gray50"))
        engine.save_preference('user_def_height', int(self.user_pref_def_height))

    def adjust_def_area_height(self):
        self.update_idletasks()
        text = self.def_area.get("1.0", "end-1c").strip()
        if not text:
            self.def_area.configure(height=self.user_pref_def_height)
            return

        try:
            cnt = self.def_area._textbox.count("1.0", "end-1c", "displaylines")
            disp_lines = cnt[0] if cnt else len(text.splitlines())
        except Exception:
            disp_lines = len(text.splitlines())

        num_lines = max(disp_lines, len(text.splitlines()))
        font_size = self.fonts["editor"].cget("size")
        line_height = int(font_size * 1.55)
        needed_height = (num_lines * line_height) + 26
        min_height = 65

        if needed_height < self.user_pref_def_height:
            final_height = max(min_height, needed_height)
        else:
            final_height = self.user_pref_def_height

        self.def_area.configure(height=final_height)

    def on_closing(self, event=None):
        if self.lookup_server is not None:
            self.lookup_server.shutdown()
        try:
            w = self.winfo_width()
            h = self.winfo_height()
            if w >= 400 and h >= 300:
                engine.save_preferences({
                    'window_width': w, 
                    'window_height': h,
                    'user_def_height': int(self.user_pref_def_height)
                })
        except Exception as e:
            print(f"Error saving window preferences: {e}")
        self.destroy()
        return "break"

    def _setup_fonts(self):
        self.base_font_sizes = {
            "title": 19,
            "word": 32,
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
            "word": ctk.CTkFont(size=int(round(self.base_font_sizes["word"] * scale)), weight="bold"),
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

        if hasattr(self, 'def_area'):
            self.def_area.configure(font=self.fonts["editor"])
            self.ex_area.configure(font=self.fonts["editor"])
            self.sentence_text.configure(font=self.fonts["body"])
            self.log_area.configure(font=self.fonts["log"])
            self.adjust_def_area_height()

        engine.save_preference('font_scale', choice)

    def on_toggle_auto_all(self):
        val = self.auto_all_meanings_var.get()
        engine.save_preference('auto_all_meanings', val)
        if not self.current_scraped_data:
            return
        
        groups = self.current_scraped_data.get('groups', [])
        if len(groups) > 1:
            if val:
                self.sense_var.set("All meanings & examples")
                self.apply_group("all")
            else:
                first_label = self.format_group_label(0, groups[0])
                self.sense_var.set(first_label)
                self.apply_group(0)

    def on_audio_choice_changed(self):
        engine.save_preference('audio_choice', self.audio_choice.get())

    def check_triggers(self):
        try:
            try:
                text = self.lookup_requests.get_nowait()
            except Empty:
                return
            if text is None:
                self.process_clipboard()
            else:
                self.process_text(text)
        finally:
            self.after(200, self.check_triggers)

    def start_local_server(self):
        try:
            with LookupServer(self.lookup_requests) as server:
                self.lookup_server = server
                server.serve_forever(poll_interval=0.2)
        except OSError as e:
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
                audio_data = io.BytesIO(engine.download_audio(url, headers))
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                pygame.mixer.music.load(audio_data)
                pygame.mixer.music.play()
            except Exception as e:
                self.log(f"[!] Audio Playback Error: {e}")

    def log(self, message):
        self.status_label.configure(text=message)
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")
        self.update_idletasks()

    def reset_editor(self, message="Search a word, or highlight text in your PDF and use your shortcut."):
        self.word_header.configure(text="A word worth remembering.")
        self.def_area.delete("0.0", tk.END)
        self.def_area.insert("0.0", message)
        self.ex_area.delete("0.0", tk.END)
        self.sense_menu.configure(values=["Select meaning..."], state="disabled")
        self.sense_var.set("Select meaning...")
        self.all_ex_btn.configure(state="disabled")
        self.adjust_def_area_height()

    def format_group_label(self, idx, grp):
        tags = []
        if grp.get('pos'):
            tags.append(grp['pos'])
        if grp.get('guideword'):
            tags.append(grp['guideword'])
        tag_str = f"[{', '.join(tags)}] " if tags else ""
        
        first_def = grp['definitions'][0] if grp['definitions'] else ""
        count_str = f" ({len(grp['definitions'])} defs)" if len(grp['definitions']) > 1 else ""
        preview = first_def[:40] + ("..." if len(first_def) > 40 else "")
        return f"{idx + 1}. {tag_str}{preview}{count_str}"

    def populate_editor(self, data, word):
        self.word_header.configure(text=word)
        groups = data.get('groups', [])
        
        if not groups:
            self.def_area.delete("0.0", tk.END)
            self.def_area.insert("0.0", data.get('definition', 'No definition found.'))
            self.ex_area.delete("0.0", tk.END)
            if data.get('examples_raw'):
                self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in data['examples_raw']]))
            self.sense_menu.configure(values=["Default Definition"], state="disabled")
            self.sense_var.set("Default Definition")
            self.all_ex_btn.configure(state="normal")
            self.adjust_def_area_height()
            return

        menu_items = []
        for i, grp in enumerate(groups):
            menu_items.append(self.format_group_label(i, grp))
            
        if len(groups) > 1:
            menu_items.append("All meanings & examples")

        self.sense_menu.configure(values=menu_items, state="normal")
        self.all_ex_btn.configure(state="normal")
        
        if self.auto_all_meanings_var.get() and len(groups) > 1:
            self.sense_var.set("All meanings & examples")
            self.apply_group("all")
        else:
            self.sense_var.set(menu_items[0])
            self.apply_group(0)

    def apply_group(self, group_choice):
        if not self.current_scraped_data: return
        groups = self.current_scraped_data.get('groups', [])
        
        if group_choice == "all":
            group_blocks = []
            for i, grp in enumerate(groups):
                tag = f"[{grp['pos']}] " if grp.get('pos') else ""
                gw = f"({grp['guideword']}) " if grp.get('guideword') else ""
                
                if len(grp['definitions']) == 1:
                    group_blocks.append(f"{i + 1}. {tag}{gw}{grp['definitions'][0]}")
                else:
                    header = f"{i + 1}. {tag}{gw}"
                    sub_defs = [f"   {chr(ord('a') + j)}. {d}" for j, d in enumerate(grp['definitions'])]
                    group_blocks.append(header + "\n" + "\n".join(sub_defs))
            
            self.def_area.delete("0.0", tk.END)
            self.def_area.insert("0.0", "\n\n".join(group_blocks))
            
            all_ex = self.current_scraped_data.get('examples_raw', [])
            self.ex_area.delete("0.0", tk.END)
            if all_ex:
                self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in all_ex]))
        else:
            idx = int(group_choice)
            if 0 <= idx < len(groups):
                grp = groups[idx]
                tag = f"[{grp['pos']}] " if grp.get('pos') else ""
                gw = f"({grp['guideword']}) " if grp.get('guideword') else ""
                
                if len(grp['definitions']) == 1:
                    text = f"{tag}{gw}{grp['definitions'][0]}"
                else:
                    header = f"{tag}{gw}"
                    sub_defs = [f"   {chr(ord('a') + j)}. {d}" for j, d in enumerate(grp['definitions'])]
                    text = header + "\n" + "\n".join(sub_defs)
                
                self.def_area.delete("0.0", tk.END)
                self.def_area.insert("0.0", text)
                
                ex_list = grp.get('examples', [])
                if not ex_list:
                    ex_list = self.current_scraped_data.get('examples_raw', [])
                    
                self.ex_area.delete("0.0", tk.END)
                if ex_list:
                    self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in ex_list]))
                    
        self.adjust_def_area_height()

    def on_sense_changed(self, choice):
        if choice == "All meanings & examples":
            self.apply_group("all")
        else:
            try:
                idx = int(choice.split(".")[0]) - 1
                self.apply_group(idx)
            except Exception:
                self.apply_group(0)

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
        try:
            clipboard_text = pyperclip.paste().strip()
        except pyperclip.PyperclipException as e:
            self.log(f"[!] Clipboard Error: {e}")
            return
        self.process_text(clipboard_text)

    def process_text(self, text):
        text = ' '.join(text.split())
        if not text: return

        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.attributes('-topmost', False)
        
        self.focus_force()
        self.word_var.set(text)
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
        self.update_idletasks()
        
        try:
            if engine.is_duplicate(word, deck):
                self.log(f"[!] Warning: '{word}' exists in '{deck}'.")
                self.reset_editor(f"⚠️ '{word}' is already in your Anki deck!")
                return
        except Exception as e:
            self.log(f"[!] Anki Error: {e}")
            self.reset_editor("⚠️ Ensure Anki is open and AnkiConnect is installed.")
            return

        try:
            data = engine.scrape_cambridge(word, manual_url)
        except requests.RequestException as e:
            self.log(f"[!] Dictionary Error: {e}")
            self.reset_editor("Could not reach Cambridge Dictionary. Please try again.")
            return
        
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
        if not data.get(f"{self.audio_choice.get()}_audio"):
            if data['uk_audio']:
                self.audio_choice.set("uk")
            elif data['us_audio']:
                self.audio_choice.set("us")
        
        self.populate_editor(data, word)
        self.add_btn.configure(state="normal")
        count = len(data.get('groups', []))
        self.log(f"Found {count} meaning group{'s' if count != 1 else ''}. Select meaning, edit if needed, then Confirm.")

    def confirm_and_add(self):
        if not self.current_scraped_data: return
            
        deck = self.deck_var.get().strip()
        data = self.current_scraped_data
        word = data['word']
        sentence = self.sentence_text.get("1.0", tk.END).strip()
        region = self.audio_choice.get()
        
        target_audio_url = data.get(f"{region}_audio")
        target_ipa = data.get(f"{region}_ipa") or ""
        
        edited_definition = self.def_area.get("1.0", tk.END).strip()
        edited_examples = self.ex_area.get("1.0", tk.END).strip()
        separator = engine.config['templates']['example_separator']
        
        self.log("Building Anki note...")
        self.update_idletasks()
        
        audio_filename = f"ankiautomata_{region}_{word.replace(' ', '_')}.mp3"
        audio_tag = ""
        if target_audio_url:
            try:
                audio_bytes = engine.download_audio(target_audio_url, data['headers'])
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                audio_filename = engine.invoke_anki('storeMediaFile', filename=audio_filename, data=audio_base64)
                audio_tag = f"[sound:{audio_filename}]"
            except Exception as e:
                self.log(f"[!] Audio save error: {e}")
        
        bolded_definition = engine.bold_word(word, edited_definition)
        bolded_examples = engine.bold_word(word, edited_examples)
        
        def_lines = bolded_definition.replace('\r\n', '\n').split('\n')
        html_def_lines = []
        for line in def_lines:
            m = re.match(r'^( +)', line)
            if m:
                indent = '&nbsp;' * (len(m.group(1)) * 2)
                html_def_lines.append(indent + line[len(m.group(1)):])
            else:
                html_def_lines.append(line)
        bolded_definition_html = '<br>'.join(html_def_lines)
        
        bolded_examples_html = bolded_examples.replace('\r\n', '\n').replace('\n', separator)
        
        front_html = engine.config['templates']['front'].format(word=escape(word))
        highlighted_sentence = engine.format_sentence(word, sentence)
        back_html = engine.config['templates']['back_layout'].format(
            definition=bolded_definition_html, 
            examples=bolded_examples_html
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
    parser = argparse.ArgumentParser(description='Cambridge Dictionary to Anki')
    parser.add_argument('--lookup', help='search this word after opening the window')
    args = parser.parse_args()
    app = AnkiAutomataApp(initial_word=args.lookup)
    app.mainloop()
