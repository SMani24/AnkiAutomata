"""Preview and approve exact-word pronunciation alternatives on Tk's thread."""
from datetime import datetime, timezone

import customtkinter as ctk

import audio_sources


class VoiceDialog(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.data = app.current_scraped_data
        self.word = audio_sources.normalize_word(self.data['word'])
        self.search_id = app._search_id
        self.sources = audio_sources.AudioSources()
        self.rows = {}
        self.pending = len(audio_sources.ALTERNATIVE_PROVIDERS)
        self.unavailable = []
        self.title(f'Choose a voice · {self.word}')
        self.geometry('660x560')
        self.minsize(520, 420)
        self.transient(app)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Escape>', lambda event: self.close())
        self.bind('<Control-w>', lambda event: (self.close(), 'break')[1])
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text=f'Pronunciation for “{self.word}”', font=app.fonts['title']).grid(
            row=0, column=0, sticky='w', padx=24, pady=(20, 8))
        ctk.CTkLabel(self, text='Preview a recording, then choose it for this card.\nAccents are shown only when the source identifies them.',
                     anchor='w', justify='left').grid(row=1, column=0, sticky='w', padx=24)
        controls = ctk.CTkFrame(self, fg_color='transparent')
        controls.grid(row=2, column=0, sticky='ew', padx=24, pady=12)
        self.reject_button = ctk.CTkButton(controls, text='Current voice is wrong', command=self.reject_current)
        self.reject_button.pack(side='left')
        ctk.CTkButton(controls, text='Reconsider rejected', width=150,
                      command=self.reconsider).pack(side='left', padx=8)
        self.status = ctk.CTkLabel(self, text='Searching Oxford, Wiktionary and Free Dictionary…', wraplength=600,
                                   justify='left', anchor='w')
        self.status.grid(row=4, column=0, sticky='ew', padx=24, pady=(8, 16))
        self.list = ctk.CTkScrollableFrame(self)
        self.list.grid(row=3, column=0, sticky='nsew', padx=20)
        self.list.grid_columnconfigure(0, weight=1)
        self.refresh_reject_button()
        if self.data.get('audio_match_version') == 1:
            source = self.data.get('source_url')
            if source:
                for region in (app.audio_choice.get(), 'us' if app.audio_choice.get() == 'uk' else 'uk'):
                    url = audio_sources.regional_url(self.data, region)
                    if url:
                        try:
                            self.add_record(self.sources.record(self.word, 'cambridge', url, region, source,
                                                               'Cambridge Dictionary', license_url=source))
                        except ValueError:
                            pass
        selected = self.data.get('selected_audio')
        if selected:
            try:
                self.add_record(audio_sources.selected_record(self.data))
            except ValueError:
                pass
        for provider in audio_sources.ALTERNATIVE_PROVIDERS:
            app.run_task(lambda provider=provider: self.sources.fetch(self.word, provider),
                         lambda records, provider=provider: self.found(provider, records),
                         lambda error, provider=provider: self.failed(provider))
        self._focus_after = self.after(100, self.take_focus)

    def take_focus(self):
        self._focus_after = None
        if self.alive():
            self.grab_set()
            self.focus_set()

    def alive(self):
        return (not self.app._closing and self.winfo_exists() and
                self.app.current_scraped_data is self.data and self.app._search_id == self.search_id and
                not self.app._exporting)

    def refresh_reject_button(self):
        has_voice = self.data.get('selected_audio') or (not self.data.get('audio_review_required') and
                    audio_sources.regional_url(self.data, self.app.audio_choice.get()))
        self.reject_button.configure(state='normal' if has_voice else 'disabled')

    def add_record(self, record):
        record = audio_sources.validate_record(record, self.word)
        identity = record['id']
        if identity in self.rows or identity in self.data.get('rejected_audio', []):
            return
        frame = ctk.CTkFrame(self.list)
        frame.grid(row=len(self.rows), column=0, sticky='ew', pady=5)
        frame.grid_columnconfigure(0, weight=1)
        accent = record['accent'].upper() if record['accent'] != 'unknown' else 'Accent unspecified'
        ctk.CTkLabel(frame, text=f'{record["label"]} · {accent}', anchor='w', wraplength=540,
                     justify='left').grid(row=0, column=0, sticky='ew', padx=12, pady=(8, 0))
        ctk.CTkLabel(frame, text=f'{record["author"]} · {record["license_name"]}', anchor='w',
                     wraplength=540, justify='left').grid(row=1, column=0, sticky='ew', padx=12)
        actions = ctk.CTkFrame(frame, fg_color='transparent')
        actions.grid(row=2, column=0, sticky='w', padx=12, pady=8)
        preview = ctk.CTkButton(actions, text='Preview', width=95, command=lambda: self.preview(record))
        preview.pack(side='left', padx=(0, 8))
        choose = ctk.CTkButton(actions, text='Use this voice', width=120, state='disabled',
                              command=lambda: self.choose(record))
        choose.pack(side='left', padx=(0, 8))
        ctk.CTkButton(actions, text='Wrong voice', width=105, command=lambda: self.reject(record)).pack(side='left')
        self.rows[identity] = {'frame': frame, 'choose': choose, 'previewed': False, 'record': record}

    def found(self, provider, records):
        if not self.alive():
            return
        for record in sorted(records, key=lambda item: item.get('accent') != self.app.audio_choice.get()):
            try:
                self.add_record(record)
            except ValueError:
                continue
        self.finish_source()

    def failed(self, provider):
        if self.alive():
            self.unavailable.append(audio_sources.LABELS[provider])
            self.finish_source()

    def finish_source(self):
        self.pending -= 1
        if self.pending:
            self.status.configure(text=f'Searching… {self.pending} source(s) remaining. You can preview results now.')
            return
        count = sum(identity not in self.data.get('rejected_audio', []) for identity in self.rows)
        message = ('Preview a recording to enable “Use this voice”.' if count else
                   'No matching recordings found. You can keep the card without audio or retry Other voices later.')
        if self.unavailable:
            message += ' Unavailable: ' + ', '.join(self.unavailable) + '.'
        self.status.configure(text=message)

    def preview(self, record):
        if not self.alive() or record['id'] in self.data.get('rejected_audio', []):
            return
        self.status.configure(text='Loading preview…')
        def played():
            if self.alive() and record['id'] not in self.data.get('rejected_audio', []):
                row = self.rows[record['id']]
                row['previewed'] = True
                row['choose'].configure(state='normal')
                self.status.configure(text='Listen carefully. Choose this voice only if it pronounces your word correctly.')
        self.app.play_audio(record=record, on_played=played, valid=self.alive,
                            on_error=lambda error: self.status.configure(text=f'Preview failed: {error}. Try another voice.'))

    def choose(self, record):
        if not self.alive() or not self.rows[record['id']]['previewed']:
            return
        if record['id'] in self.data.get('rejected_audio', []):
            return
        self.data['selected_audio'] = {**record, 'selection': 'manual',
                                       'approved_at': datetime.now(timezone.utc).isoformat()}
        self.data.pop('audio_review_required', None)
        self.app.update_audio_ui()
        self.app.save_draft()
        self.app.log(f'Chosen pronunciation: {record["label"]} ({record["accent"].upper()}).')
        self.close()

    def reject(self, record):
        if not self.alive():
            return
        current_url = audio_sources.regional_url(self.data, self.app.audio_choice.get())
        if current_url and audio_sources.candidate_id(current_url) == record['id'] and not self.data.get('selected_audio'):
            self.data['audio_review_required'] = True
        rejected = self.data.setdefault('rejected_audio', [])
        if record['id'] not in rejected:
            rejected.append(record['id'])
        if (self.data.get('selected_audio') or {}).get('id') == record['id']:
            self.data.pop('selected_audio', None)
            self.data['audio_review_required'] = True
        self.app.stop_audio()
        row = self.rows.get(record['id'])
        if row:
            row['frame'].grid_remove()
            row['choose'].configure(state='disabled')
        self.app.update_audio_ui()
        self.app.save_draft()
        self.refresh_reject_button()
        self.status.configure(text='Recording rejected. Preview another voice; rejected recordings will not be saved.')

    def reject_current(self):
        record = self.data.get('selected_audio')
        if not record:
            url = audio_sources.regional_url(self.data, self.app.audio_choice.get())
            if not url:
                return
            record = {'id': audio_sources.candidate_id(url)}
        self.data['audio_review_required'] = True
        self.reject(record)

    def close(self):
        if self._focus_after is not None:
            self.after_cancel(self._focus_after)
            self._focus_after = None
        self.app.stop_audio()
        self.destroy()

    def reconsider(self):
        if not self.alive():
            return
        self.data['rejected_audio'] = []
        self.app.save_draft()
        self.close()
        self.app.open_voice_dialog()
