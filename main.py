import customtkinter as ctk
import tkinter as tk
from tkinter import ttk
import pyperclip
import io
import pygame
import argparse
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import engine
from PIL import Image
import typewriter_client
import audio_sources
from voice_dialog import VoiceDialog
from proxy_settings import ProxySettingsFrame
from themes import PALETTES, palette, theme, recolor_widgets
from ipc import LookupServer
from background import BackgroundTasks
from storage import StateStore

ctk.ThemeManager.theme = theme(engine.get_preference('color_scheme', 'Sage'))
ctk.set_appearance_mode(engine.get_preference('appearance', 'System'))

COLORS = palette(engine.get_preference('color_scheme', 'Sage'))
SURFACE, FIELD, MUTED, BORDER, TEXT = (COLORS[key] for key in ('surface', 'field', 'muted', 'border', 'text'))
ASSETS = Path(__file__).with_name('assets')

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
            sel_bg = COLORS['hover'][1]
        else:
            bg_color = SURFACE[0]
            text_color = TEXT[0]
            sel_bg = COLORS['accent'][0]
            
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
    def __init__(self, initial_word=None, initial_sentence=None):
        super().__init__(className='AnkiAutomata')
        self._window_icon = tk.PhotoImage(master=self, file=str(ASSETS / 'ankiautomata.png'))
        self.iconphoto(True, self._window_icon)
            
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
        self._closing = False
        self._searching = False
        self._exporting = False
        self._typewriter_sending = False
        self._search_id = 0
        self._audio_id = 0
        self._duplicate_notes = []
        self._autosave_after = None
        self._compact = False
        self.tasks = BackgroundTasks()
        self.store = StateStore()
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
                     fg_color=COLORS['accent'], text_color='white',
                     font=self.fonts['title']).grid(row=0, column=0, padx=(0, 12))
        self.brand_label = ctk.CTkLabel(self.topbar, text="AnkiAutomata", font=self.fonts['title'], anchor='w')
        self.brand_label.grid(row=0, column=1, sticky='w')
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
        self.utilities = ctk.CTkFrame(self.search_bar, fg_color='transparent')
        self.utilities.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.history_btn = self.quiet_button(self.utilities, 'Recent lookups', self.open_history, width=110)
        self.history_btn.pack(side='left')
        self.manual_btn = self.quiet_button(self.utilities, 'Use URL', self.search_manual_url, width=72)
        self.manual_btn.pack(side='left', padx=(8, 0))
        self.compact_btn = self.quiet_button(self.utilities, 'Compact mode', self.toggle_compact, width=110)
        self.compact_btn.pack(side='right')
        self.progress = ctk.CTkProgressBar(self.search_bar, height=3, mode='indeterminate')
        self.progress.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(6, 0))
        self.progress.grid_remove()

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
        self._audio_icons = {region: ctk.CTkImage(
            light_image=Image.open(ASSETS / f'audio-{region}-light.png'),
            dark_image=Image.open(ASSETS / f'audio-{region}-dark.png'), size=(56, 28)) for region in ('uk', 'us')}
        self.uk_btn = self.quiet_button(self.audio_frame, '', lambda: self.play_audio('uk'),
                                        image=self._audio_icons['uk'], width=72)
        self.uk_btn.pack(side='left')
        self.uk_ipa_label = ctk.CTkLabel(self.audio_frame, text='—', font=self.fonts['body'], text_color=MUTED)
        self.uk_ipa_label.pack(side='left', padx=(8, 24))
        self.us_btn = self.quiet_button(self.audio_frame, '', lambda: self.play_audio('us'),
                                        image=self._audio_icons['us'], width=72)
        self.us_btn.pack(side='left')
        self.us_ipa_label = ctk.CTkLabel(self.audio_frame, text='—', font=self.fonts['body'], text_color=MUTED)
        self.us_ipa_label.pack(side='left', padx=8)
        self.selected_voice_btn = self.quiet_button(self.audio_frame, '▶ Chosen voice',
                                                     lambda: self.play_audio('selected'), width=150)
        self.other_voices_btn = self.quiet_button(self.audio_frame, 'Other voices…', self.open_voice_dialog, width=115)
        self.other_voices_btn.pack(side='right', padx=(8, 0))
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

        self.duplicate_frame = ctk.CTkFrame(self, fg_color=('#FFF3D5', '#3A3423'), corner_radius=10)
        self.duplicate_frame.grid_columnconfigure(0, weight=1)
        self.duplicate_label = ctk.CTkLabel(self.duplicate_frame, text='', anchor='w', justify='left',
            text_color=('#6D501D', '#E0C88D'), font=self.fonts['small'])
        self.duplicate_label.grid(row=0, column=0, sticky='ew', padx=16, pady=12)
        self.open_note_btn = self.quiet_button(self.duplicate_frame, 'Open in Anki', self.open_existing_note, width=110)
        self.open_note_btn.grid(row=0, column=1, padx=(0, 12))

        self.submit_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.submit_frame.grid(row=4, column=0, sticky='ew', padx=28, pady=(16, 10))
        self.submit_frame.grid_columnconfigure(0, weight=1)
        self.audio_choice = tk.StringVar(value=engine.get_preference('audio_choice', 'uk'))
        self.audio_save_frame = ctk.CTkFrame(self.submit_frame, fg_color='transparent')
        self.audio_save_frame.grid(row=0, column=0, sticky='w')
        self.audio_save_label = ctk.CTkLabel(self.audio_save_frame, text='Save pronunciation',
                                            font=self.fonts['small'], text_color=MUTED)
        self.audio_save_label.pack(side='left', padx=(0, 16))
        self.audio_region_buttons = []
        for region in ('uk', 'us'):
            button = ctk.CTkRadioButton(self.audio_save_frame, text=region.upper(), variable=self.audio_choice,
                value=region, font=self.fonts['body'], width=62, radiobutton_width=18,
                radiobutton_height=18, command=self.on_audio_choice_changed)
            button.pack(side='left', padx=(0, 8))
            self.audio_region_buttons.append(button)
        self.add_btn = ctk.CTkButton(self.submit_frame, text='Add to Anki', width=180,
            height=44, font=self.fonts['btn_large'], state='disabled', command=self.confirm_and_add)
        self.typewriter_btn = self.quiet_button(self.submit_frame, 'Send to Typewriter', self.send_to_typewriter, width=150)
        self.typewriter_btn.grid(row=0, column=1, padx=(8, 12))
        self.typewriter_btn.configure(state='disabled')
        self.add_btn.grid(row=0, column=2, sticky='e')

        self.status_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.status_frame.grid(row=5, column=0, sticky='ew', padx=28, pady=(0, 12))
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.status_frame, text='Ready · Select text in your PDF to begin',
            font=self.fonts['small'], text_color=MUTED, anchor='w')
        self.status_label.grid(row=0, column=0, sticky='ew')
        self.activity_btn = self.quiet_button(self.status_frame, 'Activity', self.toggle_activity, width=70)
        self.activity_btn.grid(row=0, column=1)
        self.log_area = ctk.CTkTextbox(self, height=100, font=self.fonts['log'], state='disabled')

        self.word_entry.bind('<Return>', lambda event: self.search_word())
        for shortcut in ('<Control-a>', '<Control-A>', '<Command-a>', '<Command-A>'):
            self.word_entry.bind(shortcut, self.select_search_all)
        self.word_entry.focus()
        self.word_var.trace_add('write', lambda *_: self.schedule_autosave())
        for editor in (self.def_area, self.ex_area, self.sentence_text):
            editor.bind('<KeyRelease>', lambda event: self.schedule_autosave(), add='+')
        self.bind('<Control-Return>', self.add_shortcut)
        for editor in (self.word_entry, self.def_area, self.ex_area, self.sentence_text):
            editor.bind('<Control-Return>', self.add_shortcut)
        self.bind('<Control-l>', self.focus_search)
        self.bind('<Control-Shift-M>', lambda event: self.toggle_compact())
        self.bind('<Escape>', self.dismiss_compact)
        self.bind('<Configure>', self._on_window_resize)
        self._full_geometry = self.geometry()
        self._poll_after = self.after(50, self.poll_tasks)
        if engine.get_preference('compact_mode', False):
            self.toggle_compact()
        if self.store.draft and not initial_word:
            self.restore_snapshot(self.store.draft)
        if self.store.error:
            self.log(f'Saved draft could not be read: {self.store.error}')
        self.server_thread = threading.Thread(target=self.start_local_server, daemon=True)
        self.server_thread.start()
        if initial_word:
            self.lookup_requests.put_nowait({'text': initial_word, 'sentence': initial_sentence}
                                              if initial_sentence is not None else initial_word)
        self._trigger_after = self.after(200, self.check_triggers)

    def quiet_button(self, parent, text, command, **kwargs):
        return ctk.CTkButton(parent, text=text, command=command, font=self.fonts['small'],
            height=32, fg_color='transparent', hover_color=BORDER, text_color=TEXT, **kwargs)

    def toggle_activity(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_area.grid(row=6, column=0, sticky='ew', padx=28, pady=(0, 16))
        else:
            self.log_area.grid_remove()

    def open_settings(self):
        previous = getattr(self, '_settings_dialog', None)
        if previous is not None and previous.winfo_exists():
            previous.lift()
            return previous
        dialog = ctk.CTkToplevel(self)
        self._settings_dialog = dialog
        dialog.title('Settings')
        dialog.geometry('520x660')
        dialog.minsize(480, 560)
        dialog.transient(self)
        dialog.grab_set()
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        tabs = ctk.CTkTabview(dialog)
        tabs.pack(fill='both', expand=True, padx=12, pady=12)
        appearance_tab = tabs.add('Appearance')
        network_tab = tabs.add('Network')
        preferences = ctk.CTkScrollableFrame(appearance_tab, fg_color='transparent')
        preferences.pack(fill='both', expand=True)
        ctk.CTkLabel(preferences, text='Make it yours', font=self.fonts['title']).pack(anchor='w', padx=24, pady=(24, 18))
        ctk.CTkLabel(preferences, text='Appearance', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24)
        appearance = ctk.CTkOptionMenu(preferences, values=['System', 'Light', 'Dark'], command=self.on_appearance_changed)
        appearance.set(engine.get_preference('appearance', 'System'))
        appearance.pack(fill='x', padx=24, pady=(6, 14))
        ctk.CTkLabel(preferences, text='Color scheme', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24)
        scheme = ctk.CTkOptionMenu(preferences, values=list(PALETTES), command=self.on_color_scheme_changed)
        scheme.set(engine.get_preference('color_scheme', 'Sage'))
        scheme.pack(fill='x', padx=24, pady=(6, 14))
        ctk.CTkLabel(preferences, text='Text size', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24)
        scale = ctk.CTkOptionMenu(preferences, values=list(self.font_scale_factors), command=self.on_font_scale_changed)
        scale.set(self.current_scale_choice)
        scale.pack(fill='x', padx=24, pady=(6, 18))
        ctk.CTkSwitch(preferences, text='Combine all meanings by default', variable=self.auto_all_meanings_var,
                       command=self.on_toggle_auto_all, font=self.fonts['small']).pack(anchor='w', padx=24)
        ctk.CTkLabel(preferences, text='Pronunciation saved to Anki', font=self.fonts['small'], text_color=MUTED).pack(anchor='w', padx=24, pady=(18, 6))
        audio = ctk.CTkOptionMenu(preferences, values=['UK', 'US'], command=lambda value: self.set_audio_preference(value.lower()))
        audio.set(self.audio_choice.get().upper())
        audio.pack(fill='x', padx=24)

        dialog.network_settings = ProxySettingsFrame(network_tab, self)
        dialog.network_settings.pack(fill='both', expand=True)
        dialog.tabs = tabs
        return dialog

    def on_appearance_changed(self, choice):
        ctk.set_appearance_mode(choice)
        engine.save_preference('appearance', choice)

    def on_color_scheme_changed(self, name):
        global COLORS, SURFACE, FIELD, MUTED, BORDER, TEXT
        old = COLORS
        COLORS = palette(name)
        SURFACE, FIELD, MUTED, BORDER, TEXT = (COLORS[key] for key in ('surface', 'field', 'muted', 'border', 'text'))
        ctk.ThemeManager.theme = theme(name)
        recolor_widgets(self, old, COLORS)
        engine.save_preference('color_scheme', name)

    def select_search_all(self, event=None):
        self.word_entry.select_range(0, 'end')
        self.word_entry.icursor('end')
        return 'break'

    def focus_search(self, event=None):
        self.word_entry.focus_set()
        self.word_entry.select_range(0, 'end')
        return 'break'

    def add_shortcut(self, event=None):
        self.confirm_and_add()
        return 'break'

    def _on_window_resize(self, event):
        if event.widget is self:
            width = max(180, event.width - 120)
            self.word_header.configure(wraplength=width)
            self.status_label.configure(wraplength=width)
            self.duplicate_label.configure(wraplength=max(160, width - 130))

    def toggle_compact(self):
        self.update_idletasks()
        self._compact = not self._compact
        if self._compact:
            self._full_geometry = self.geometry()
            height = self.compact_minimum_height()
            self.minsize(540, height)
            self.geometry(f'640x{max(720, height)}+{max(0, self.winfo_screenwidth() - 680)}+60')
            for widget in (self.brand_label, self.deck_display, self.context_frame, self.audio_save_frame):
                widget.grid_remove()
            self.uk_ipa_label.pack_forget()
            self.us_ipa_label.pack_forget()
            self.compact_btn.configure(text='Full editor')
            self.deck_btn.configure(text='Deck')
            if self._log_visible:
                self.toggle_activity()
        else:
            self.minsize(840, 720)
            self.geometry(self._full_geometry)
            for widget in (self.brand_label, self.deck_display, self.context_frame, self.audio_save_frame):
                widget.grid()
            self.compact_btn.configure(text='Compact mode')
            self.deck_btn.configure(text='Change deck')
        self.update_audio_ui()
        self.adjust_def_area_height()
        engine.save_preference('compact_mode', self._compact)

    def compact_minimum_height(self):
        scale = self.font_scale_factors[self.current_scale_choice]
        return 700 + round((scale - 1) * 150) + (80 if self._duplicate_notes else 0)

    def dismiss_compact(self, event=None):
        if self._compact:
            self.save_draft()
            self.iconify()
            return 'break'

    def run_task(self, operation, success, failure=None):
        if failure is None:
            failure = lambda error: self.log(f'Could not complete the action: {error}')
        try:
            self.tasks.submit(operation, success, failure)
        except Full:
            failure(RuntimeError('Background queue is busy. Please try again shortly.'))

    def poll_tasks(self):
        try:
            self.tasks.poll()
        finally:
            if not self._closing:
                self._poll_after = self.after(50, self.poll_tasks)

    def snapshot(self):
        data = self.current_scraped_data
        query = self.word_var.get().strip()
        word = data['word'] if data else query
        if not word:
            return None
        return {'word': word, 'query': query, 'data': data,
                'definition': self.def_area.get('1.0', 'end-1c') if data else '',
                'examples': self.ex_area.get('1.0', 'end-1c') if data else '',
                'sentence': self.sentence_text.get('1.0', 'end-1c'),
                'deck': self.deck_var.get(), 'audio': self.audio_choice.get(),
                'sense': self.sense_var.get()}

    def schedule_autosave(self):
        if self._closing:
            return
        if self._autosave_after is not None:
            self.after_cancel(self._autosave_after)
        self._autosave_after = self.after(600, self.save_draft)

    def save_draft(self):
        if self._autosave_after is not None:
            self.after_cancel(self._autosave_after)
        self._autosave_after = None
        if self._searching:
            return
        try:
            self.store.save_draft(self.snapshot())
        except OSError as error:
            self.log(f'Draft could not be saved: {error}')

    def restore_snapshot(self, snapshot):
        if self._exporting:
            return
        self.close_voice_dialog()
        self.save_draft()
        self._search_id += 1
        self._audio_id += 1
        self.set_searching(False)
        self.current_scraped_data = snapshot.get('data')
        if self.current_scraped_data:
            self.store.restore_audio_choices(self.current_scraped_data)
        if self.current_scraped_data and self.current_scraped_data.get('audio_match_version') != 1:
            self.current_scraped_data = dict(self.current_scraped_data)
            self.current_scraped_data['audio_needs_refresh'] = True
            for region in ('uk', 'us'):
                self.current_scraped_data[f'{region}_audio'] = None
                self.current_scraped_data[f'{region}_ipa'] = ''
        self.word_var.set(snapshot.get('query', snapshot['word']))
        self.deck_var.set(snapshot.get('deck') or self.deck_var.get())
        self.audio_choice.set(snapshot.get('audio', 'uk'))
        self.set_duplicates([])
        if self.current_scraped_data:
            self.populate_editor(self.current_scraped_data, snapshot['word'])
            if snapshot.get('sense'):
                self.on_sense_changed(snapshot['sense'])
            for editor, key in ((self.def_area, 'definition'), (self.ex_area, 'examples')):
                editor.delete('1.0', 'end')
                editor.insert('1.0', snapshot.get(key, ''))
            self.sense_var.set(snapshot.get('sense') or self.sense_var.get())
        else:
            self.reset_editor()
        self.sentence_text.delete('1.0', 'end')
        self.sentence_text.insert('1.0', snapshot.get('sentence', ''))
        self.update_audio_ui()
        self.adjust_def_area_height()
        self.log(f'Restored draft for {snapshot["word"]}.')
        self.save_draft()
        self.recheck_duplicates()

    def open_history(self):
        if self._exporting:
            return
        self.save_draft()
        dialog = ctk.CTkToplevel(self)
        dialog.title('Recent lookups')
        dialog.geometry('480x540')
        dialog.transient(self)
        dialog.grab_set()
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        ctk.CTkLabel(dialog, text='Pick up where you left off', font=self.fonts['title']).pack(
            anchor='w', padx=24, pady=24)
        listing = ctk.CTkScrollableFrame(dialog, fg_color='transparent')
        listing.pack(fill='both', expand=True, padx=16, pady=(0, 16))
        if not self.store.history:
            ctk.CTkLabel(listing, text='Your recent words will appear here.', text_color=MUTED).pack(pady=24)
        for snapshot in self.store.history:
            def restore(item=snapshot):
                dialog.destroy()
                self.restore_snapshot(item)
            label = snapshot['word'] + '\n' + (snapshot.get('deck') or 'Draft')
            ctk.CTkButton(listing, text=label, anchor='w', height=64, fg_color=FIELD,
                hover_color=BORDER, text_color=TEXT, font=self.fonts['body'], command=restore).pack(
                fill='x', padx=4, pady=4)

    def set_searching(self, value):
        self._searching = value
        self.deck_btn.configure(state='disabled' if value or self._exporting else 'normal')
        if value:
            self.progress.grid()
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.grid_remove()
        self.refresh_add_state()

    def refresh_add_state(self):
        enabled = (self.current_scraped_data is not None and not self._searching
                   and not self._exporting and not self._duplicate_notes)
        self.add_btn.configure(state='normal' if enabled else 'disabled')
        can_send = self.current_scraped_data is not None and not self._searching and not self._exporting and not self._typewriter_sending
        self.typewriter_btn.configure(state='normal' if can_send else 'disabled')

    def set_duplicates(self, notes):
        self._duplicate_notes = notes
        if notes:
            preview = engine.note_preview(notes[0])[:90]
            self.duplicate_label.configure(text='Already in this deck' + (' · ' + preview if preview else ''))
            self.duplicate_frame.grid(row=3, column=0, sticky='ew', padx=28, pady=(12, 0))
        else:
            self.duplicate_frame.grid_remove()
        if self._compact:
            self.minsize(540, self.compact_minimum_height())
        self.refresh_add_state()

    def open_existing_note(self):
        notes = list(self._duplicate_notes)
        self.run_task(lambda: engine.open_notes(notes), lambda _: self.log('Opened the existing card in Anki.'))

    def recheck_duplicates(self):
        if not self.current_scraped_data:
            return
        self._search_id += 1
        token = self._search_id
        word, deck = self.current_scraped_data['word'], self.deck_var.get()
        self.set_searching(True)
        self.set_duplicates([])
        def done(notes):
            if token != self._search_id:
                return
            self.set_searching(False)
            self.set_duplicates(notes)
            self.log('Existing card found. Open it in Anki to review.' if notes else 'Ready to add to Anki.')
            self.save_draft()
        def failed(error):
            if token != self._search_id:
                return
            self.set_searching(False)
            self.log(f'Anki is unavailable. Your draft is safe; retry Add when Anki is running. {error}')
            self.save_draft()
        self.run_task(lambda: engine.find_duplicate_notes(word, deck), done, failed)

    def update_audio_ui(self):
        data = self.current_scraped_data or {}
        try:
            selected = audio_sources.selected_record(data)
        except ValueError:
            data.pop('selected_audio', None)
            data['audio_review_required'] = True
            selected = None
        self.other_voices_btn.configure(state='normal' if data and not self._exporting else 'disabled')
        self.update_save_audio_ui(selected, data.get('audio_review_required', False))
        self.selected_voice_btn.pack_forget()
        for region, button, label in (('uk', self.uk_btn, self.uk_ipa_label),
                                       ('us', self.us_btn, self.us_ipa_label)):
            button.configure(state='normal' if audio_sources.regional_url(data, region) else 'disabled')
            label.configure(text=data.get(f'{region}_ipa') or '—')
            button.pack_forget()
            label.pack_forget()
            if not selected:
                button.pack(side='left')
                if not self._compact:
                    label.pack(side='left', padx=(8, 12))
        if selected:
            self.selected_voice_btn.pack(side='left')
            accent = selected['accent'].upper() if selected['accent'] != 'unknown' else 'Accent unspecified'
            self.word_meta.configure(text=f'AUDIO: {selected["label"]} · {accent}')
            return
        if not audio_sources.regional_url(data, self.audio_choice.get()):
            for region in ('uk', 'us'):
                if audio_sources.regional_url(data, region):
                    self.audio_choice.set(region)
                    break
        ipa = data.get(f'{self.audio_choice.get()}_ipa') or ''
        self.word_meta.configure(text='Choose another voice · card will be saved without audio until then' if data.get('audio_review_required') else
                                 'Search again to refresh pronunciation' if data.get('audio_needs_refresh') else
                                 (ipa + ' · ' if self._compact and ipa else '') + 'CAMBRIDGE DICTIONARY')

    def update_save_audio_ui(self, selected=None, review=False):
        if not hasattr(self, 'audio_save_label'):
            return
        self.audio_save_label.configure(text='Save chosen voice' if selected else
                                        'Save without audio' if review else 'Save pronunciation')
        for button in self.audio_region_buttons:
            button.pack_forget()
            if not selected and not review:
                button.pack(side='left', padx=(0, 8))

    def close_voice_dialog(self):
        dialog = getattr(self, '_voice_dialog', None)
        if dialog is not None and dialog.winfo_exists():
            dialog.close()
        self._voice_dialog = None

    def stop_audio(self):
        self._audio_id += 1
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()

    def open_voice_dialog(self):
        if not self.current_scraped_data or self._exporting or self._searching:
            return
        dialog = getattr(self, '_voice_dialog', None)
        if dialog is not None and dialog.winfo_exists():
            dialog.lift()
            return
        self._voice_dialog = VoiceDialog(self)

    # --- Height Splitter Logic ---
    def _on_splitter_press(self, event):
        self._is_dragging_splitter = True
        self._drag_start_y = event.y_root
        h = self.def_area.winfo_height()
        self._drag_start_h = h if h > 1 else self.def_area.cget("height")
        self.splitter.configure(fg_color=COLORS['accent'])

    def _on_splitter_drag(self, event):
        if not self._is_dragging_splitter: return
        delta = event.y_root - self._drag_start_y
        new_h = self._drag_start_h + delta
        
        min_h = 55
        max_h = max(min_h, self.def_area.winfo_height() + self.ex_area.winfo_height() - 80)
        
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

        preferred = min(self.user_pref_def_height, 100) if self._compact else self.user_pref_def_height
        if needed_height < preferred:
            final_height = max(min_height, needed_height)
        else:
            final_height = preferred

        self.def_area.configure(height=final_height)

    def on_closing(self, event=None):
        self.save_draft()
        self._closing = True
        self.tasks.close()
        for timer in (self._autosave_after, self._poll_after, self._trigger_after):
            if timer is not None:
                self.after_cancel(timer)
        if self.lookup_server is not None:
            self.lookup_server.shutdown()
        try:
            geometry = self._full_geometry if self._compact else self.geometry()
            size = geometry.split('+')[0].split('-')[0]
            width, height = (int(value) for value in size.split('x'))
            engine.save_preferences({'window_width': width, 'window_height': height,
                                     'user_def_height': int(self.user_pref_def_height)})
        except (ValueError, tk.TclError) as error:
            print(f'Error saving window preferences: {error}')
        # CTk also owns delayed redraws; cancel them before their Tcl commands disappear.
        for timer in self.tk.call('after', 'info'):
            self.tk.call('after', 'cancel', timer)
        self.destroy()
        return 'break'

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
        if self._compact:
            self.minsize(540, self.compact_minimum_height())

    def on_toggle_auto_all(self):
        if self._exporting:
            return
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

    def set_audio_preference(self, region):
        self.audio_choice.set(region)
        self.on_audio_choice_changed()

    def on_audio_choice_changed(self):
        engine.save_preference('audio_choice', self.audio_choice.get())
        self.update_audio_ui()
        self.schedule_autosave()

    def check_triggers(self):
        try:
            if self._exporting:
                return
            try:
                text = self.lookup_requests.get_nowait()
            except Empty:
                return
            if text is None:
                self.process_clipboard()
            elif isinstance(text, dict):
                if text.get('action') == 'activate':
                    self.activate_window()
                else:
                    self.process_text(text['text'], text.get('sentence'))
            else:
                self.process_text(text)
        finally:
            self._trigger_after = self.after(200, self.check_triggers)

    def start_local_server(self):
        try:
            with LookupServer(self.lookup_requests) as server:
                self.lookup_server = server
                server.serve_forever(poll_interval=0.2)
        except OSError as e:
            print(f"Local server error: {e}")

    def change_deck(self):
        if self._exporting or self._searching:
            return
        self.deck_btn.configure(state='disabled')
        def show(decks):
            self.deck_btn.configure(state='normal')
            current = self.deck_var.get()
            if current not in decks:
                decks = list(decks) + [current]
            dialog = DeckSelectionDialog(self, decks, current, font=self.fonts['btn'])
            self.wait_window(dialog)
            if not self._closing and dialog.selected_deck:
                self.deck_var.set(dialog.selected_deck)
                engine.save_preference('selected_deck', dialog.selected_deck)
                self.save_draft()
                self.recheck_duplicates()
        def failed(error):
            self.deck_btn.configure(state='normal')
            self.log(f'Could not load decks. Ensure Anki is running. {error}')
        self.run_task(lambda: engine.invoke_anki('deckNames'), show, failed)

    def auto_bullet(self, event):
        self.ex_area.insert("insert", "\n• ")
        self.ex_area.see("insert")
        return "break" 

    def play_audio(self, region=None, record=None, on_played=None, valid=None, on_error=None):
        data = self.current_scraped_data
        if not data:
            return
        try:
            if region == 'selected':
                record = audio_sources.selected_record(data)
            if record:
                record = audio_sources.validate_record(record, audio_sources.normalize_word(data['word']))
                if record['id'] in data.get('rejected_audio', []):
                    return
            elif not audio_sources.regional_url(data, region):
                return
        except ValueError as error:
            self.log(str(error))
            return
        self._audio_id += 1
        token = self._audio_id
        label = record['label'] if record else region.upper()
        self.log(f'Loading {label} pronunciation…')
        def ready(content):
            if token != self._audio_id or self.current_scraped_data is not data or (valid and not valid()):
                return
            try:
                if not pygame.mixer.get_init():
                    pygame.mixer.init()
                self._audio_stream = io.BytesIO(content)
                pygame.mixer.music.load(self._audio_stream)
                pygame.mixer.music.play()
                self.log(f'Playing {label} pronunciation.')
                if on_played:
                    on_played()
            except pygame.error as error:
                failed(error, alternatives=False)
        def failed(error, alternatives=True):
            if token == self._audio_id and (not valid or valid()):
                self.log(f'Audio download failed: {error}')
                if on_error:
                    on_error(error)
                elif alternatives:
                    self.open_voice_dialog()
        if record:
            operation = lambda: audio_sources.AudioSources().recording(record)
        else:
            url, headers = audio_sources.regional_url(data, region), data.get('headers', {})
            operation = lambda: engine.download_audio(url, headers)
        self.run_task(operation, ready, failed)

    def log(self, message):
        self.status_label.configure(text=message)
        self.log_area.configure(state="normal")
        self.log_area.insert("end", message + "\n")
        self.log_area.see("end")
        self.log_area.configure(state="disabled")
        self.update_idletasks()

    def reset_editor(self, message="Search a word, or highlight text in your PDF and use your shortcut."):
        self.word_header.configure(text='Look up a word.' if self._compact else 'A word worth remembering.')
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
        if self._exporting:
            return
        if not self.current_scraped_data: return
        groups = self.current_scraped_data.get('groups', [])
        if self.current_scraped_data.get('audio_match_version') == 1:
            group = groups[int(group_choice)] if group_choice != 'all' and 0 <= int(group_choice) < len(groups) else None
            self.current_scraped_data.update(engine.pronunciation_for_group(self.current_scraped_data, group))
            self._audio_id += 1
            self.update_audio_ui()
        
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
        self.schedule_autosave()
        if choice == "All meanings & examples":
            self.apply_group("all")
        else:
            try:
                idx = int(choice.split(".")[0]) - 1
                self.apply_group(idx)
            except Exception:
                self.apply_group(0)

    def load_all_examples(self):
        self.schedule_autosave()
        if not self.current_scraped_data: return
        all_ex = self.current_scraped_data.get('examples_raw', [])
        if all_ex:
            self.ex_area.delete("0.0", tk.END)
            self.ex_area.insert("0.0", "\n".join([f"• {ex}" for ex in all_ex]))

    def reset_audio_ui(self):
        self.update_save_audio_ui()
        self.other_voices_btn.configure(state='disabled')
        self.selected_voice_btn.pack_forget()
        self.uk_btn.pack(side='left')
        self.us_btn.pack(side='left')
        if not self._compact:
            self.uk_ipa_label.pack(side='left', after=self.uk_btn, padx=(8, 12))
            self.us_ipa_label.pack(side='left', after=self.us_btn, padx=(8, 12))
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

    def process_text(self, text, sentence=None):
        text = ' '.join(text.split())
        if not text: return

        self.save_draft()
        self.current_scraped_data = None
        self.activate_window()
        self.word_var.set(text)
        if sentence is not None:
            self.sentence_text.delete('1.0', 'end')
            self.sentence_text.insert('1.0', sentence)
        self.search_word()

    def activate_window(self):
        self.deiconify()
        self.lift()
        self.attributes('-topmost', True)
        self.attributes('-topmost', False)
        self.focus_force()

    def send_to_typewriter(self):
        if not self.current_scraped_data or self._typewriter_sending or self._exporting or self._searching:
            return
        try:
            item = typewriter_client.prepare_word(self.snapshot())
        except ValueError as error:
            self.log(str(error))
            return
        self.save_draft()
        self._typewriter_sending = True
        self.typewriter_btn.configure(text='Sending…')
        self.refresh_add_state()
        address = engine.get_preference('typewriter_url', 'http://127.0.0.1:8080')
        def finish():
            self._typewriter_sending = False
            self.typewriter_btn.configure(text='Send to Typewriter')
            self.refresh_add_state()
        def done(result):
            finish()
            self.log(f'{item["word"]} already exists in Typewriter; its progress was preserved.' if result['duplicates']
                     else f'Sent {item["word"]} to Typewriter.')
        def failed(error):
            finish()
            self.log(f'Could not send to Typewriter. Start it on {address} and try again. {error}')
        self.run_task(lambda: typewriter_client.send_word(item, address), done, failed)

    def search_word(self, manual_url=None):
        if self._exporting:
            return
        word = ' '.join(self.word_var.get().split())
        if not word:
            return
        self.close_voice_dialog()
        self.save_draft()
        self._search_id += 1
        self._audio_id += 1
        token = self._search_id
        deck = self.deck_var.get().strip()
        self.current_scraped_data = None
        self.set_duplicates([])
        self.reset_audio_ui()
        self.reset_editor('Searching Cambridge Dictionary…')
        self.set_searching(True)
        self.log(f'Looking up {word}…')
        def lookup():
            data = engine.scrape_cambridge(word, manual_url)
            duplicates, anki_error = [], None
            if data:
                try:
                    duplicates = engine.find_duplicate_notes(word, deck)
                except Exception as error:
                    anki_error = str(error)
            return data, duplicates, anki_error
        self.run_task(lookup,
            lambda result: self.lookup_finished(token, word, manual_url, result),
            lambda error: self.lookup_failed(token, error))

    def search_manual_url(self):
        if self._exporting:
            return
        dialog = ctk.CTkInputDialog(text='Paste a direct Cambridge Dictionary URL:', title='Find another entry')
        url = dialog.get_input()
        if url and not self._closing:
            self.search_word(manual_url=url.strip())

    def lookup_failed(self, token, error):
        if token != self._search_id:
            return
        self.set_searching(False)
        self.reset_editor('Could not reach Cambridge Dictionary. Please try again.')
        self.log(f'Dictionary lookup failed: {error}')

    def lookup_finished(self, token, word, manual_url, result):
        if token != self._search_id:
            return
        self.set_searching(False)
        data, duplicates, anki_error = result
        if not data:
            self.reset_editor('No entry found. Try another spelling or choose Use URL.')
            self.log(f'No entry found for {word}. You can paste a direct dictionary link with Use URL.')
            return
        self.current_scraped_data = data
        self.store.restore_audio_choices(data)
        self.populate_editor(data, word)
        self.update_audio_ui()
        self.set_duplicates(duplicates)
        if duplicates:
            self.log('Existing card found. Open it in Anki to review, or choose another deck.')
        elif anki_error:
            self.log(f'Dictionary ready. Start Anki before adding. {anki_error}')
        else:
            count = len(data.get('groups', []))
            self.log(f'{count} meaning group{"s" if count != 1 else ""} · Review your card, then add it to Anki.')
        self.save_draft()

        if data.get('audio_match_version') == 1 and not data.get('selected_audio') and (
                data.get('audio_review_required') or not any(audio_sources.regional_url(data, r) for r in ('uk', 'us'))):
            self.open_voice_dialog()

    def set_exporting(self, value):
        self._exporting = value
        if value:
            self.close_voice_dialog()
        for widget in (self.word_entry, self.def_area, self.ex_area, self.sentence_text,
                       self.search_btn, self.deck_btn, self.history_btn, self.manual_btn):
            widget.configure(state='disabled' if value else 'normal')
        self.sense_menu.configure(state='disabled' if value else 'normal')
        self.add_btn.configure(text='Adding…' if value else 'Add to Anki')
        self.refresh_add_state()

    def confirm_and_add(self):
        if not self.current_scraped_data or self._exporting or self._searching or self._duplicate_notes:
            return
        snapshot = self.snapshot()
        if not snapshot['definition'].strip():
            self.log('Add a definition before saving the card.')
            return
        self.save_draft()
        self.set_exporting(True)
        self.log(f'Adding {snapshot["word"]} to Anki…')
        def done(result):
            self.set_exporting(False)
            if result.get('duplicates'):
                self.set_duplicates(result['duplicates'])
                self.log('This word was already added. Open the existing card in Anki.')
                return
            self.current_scraped_data = None
            self._audio_id += 1
            self.word_var.set('')
            self.sentence_text.delete('1.0', 'end')
            self.reset_editor('Ready for your next discovery.')
            self.reset_audio_ui()
            self.refresh_add_state()
            self.save_draft()
            warnings = result.get('warnings', [])
            self.log(f'Added {snapshot["word"]} to {snapshot["deck"]}.' + (' ' + ' '.join(warnings) if warnings else ''))
            self.word_entry.focus_set()
        def failed(error):
            self.set_exporting(False)
            self.log(f'Could not add the card. Your draft is safe. {error}')
        self.run_task(lambda: engine.export_note(snapshot), done, failed)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Cambridge Dictionary to Anki')
    parser.add_argument('--lookup', help='search this word after opening the window')
    parser.add_argument('--sentence', help='sentence context for the initial lookup')
    args = parser.parse_args()
    app = AnkiAutomataApp(initial_word=args.lookup, initial_sentence=args.sentence)
    app.mainloop()
