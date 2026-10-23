"""Settings controls for the app's internet route."""
import tkinter as tk

import customtkinter as ctk

import network


class ProxySettingsFrame(ctk.CTkScrollableFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color='transparent')
        self.app = app
        self.testing = False
        self.test_id = 0
        self.grid_columnconfigure(1, weight=1)
        error = None
        try:
            values = network.load_settings()
        except network.NetworkError as exception:
            values = dict(network.DEFAULTS)
            error = str(exception)
        self.enabled = tk.BooleanVar(master=self, value=values['enabled'])
        ctk.CTkLabel(self, text='Internet proxy', font=app.fonts['title']).grid(
            row=0, column=0, columnspan=2, sticky='w', padx=12, pady=(8, 10))
        self.enabled_switch = ctk.CTkSwitch(self, text='Route internet requests through a proxy',
                                           variable=self.enabled, command=self.changed)
        self.enabled_switch.grid(row=1, column=0, columnspan=2, sticky='w', padx=12, pady=(0, 12))
        self.protocol = ctk.CTkOptionMenu(self, values=list(network.PROTOCOLS), command=self.changed)
        self.protocol.set(next(label for label, value in network.PROTOCOLS.items() if value == values['type']))
        self.host = ctk.CTkEntry(self)
        self.host.insert(0, values['host'])
        self.port = ctk.CTkEntry(self)
        self.port.insert(0, str(values['port']))
        self.username = ctk.CTkEntry(self, placeholder_text='Optional')
        self.username.insert(0, values['username'])
        self.password = ctk.CTkEntry(self, show='•', placeholder_text='Optional')
        self.password.insert(0, values['password'])
        for row, label, widget in ((2, 'Protocol', self.protocol), (3, 'Host', self.host),
                                   (4, 'Port', self.port), (5, 'Username', self.username),
                                   (6, 'Password', self.password)):
            ctk.CTkLabel(self, text=label).grid(row=row, column=0, sticky='w', padx=12, pady=6)
            widget.grid(row=row, column=1, sticky='ew', padx=12, pady=6)
            if widget is not self.protocol:
                widget.bind('<KeyRelease>', self.changed, add='+')
        self.show_password = tk.BooleanVar(master=self, value=False)
        ctk.CTkCheckBox(self, text='Show password', variable=self.show_password,
                        command=lambda: self.password.configure(show='' if self.show_password.get() else '•')).grid(
            row=7, column=1, sticky='w', padx=12, pady=(4, 10))
        ctk.CTkLabel(self, text='Applies to dictionary lookups and all pronunciation sources.\n'
                     'Local Anki and Typewriter connections stay direct.\n'
                     'Turning this off uses a direct connection, ignoring system proxies.',
                     justify='left', wraplength=400).grid(row=8, column=0, columnspan=2, sticky='w', padx=12, pady=10)
        actions = ctk.CTkFrame(self, fg_color='transparent')
        actions.grid(row=9, column=0, columnspan=2, sticky='ew', padx=12, pady=(4, 8))
        self.test_button = ctk.CTkButton(actions, text='Test connection', width=145, command=self.test)
        self.test_button.pack(side='left')
        self.save_button = ctk.CTkButton(actions, text='Save network settings', width=175, command=self.save)
        self.save_button.pack(side='left', padx=(12, 0))
        self.status = ctk.CTkLabel(self, text=error or 'Changes take effect after saving. Test uses the values shown above.',
                                   wraplength=400, justify='left', anchor='w')
        self.status.grid(row=10, column=0, columnspan=2, sticky='ew', padx=12, pady=8)
        ctk.CTkLabel(self, text='Saved locally in your user configuration folder.\n'
                     'Credentials are stored in an owner-only file, separate from the repository.',
                     wraplength=400, justify='left').grid(row=11, column=0, columnspan=2, sticky='w', padx=12, pady=8)

    def values(self):
        try:
            port = int(self.port.get().strip())
        except ValueError:
            raise ValueError('Proxy port must be a whole number between 1 and 65535.') from None
        return network.validate_settings({
            'enabled': self.enabled.get(), 'type': network.PROTOCOLS[self.protocol.get()],
            'host': self.host.get(), 'port': port, 'username': self.username.get(), 'password': self.password.get(),
        })

    def changed(self, event=None):
        self.test_id += 1
        self.status.configure(text='Unsaved changes. Test the settings or save to apply them.')

    def save(self):
        try:
            settings = network.save_settings(self.values())
        except (ValueError, network.NetworkError) as error:
            self.status.configure(text=str(error))
            return
        self.test_id += 1
        self.status.configure(text='Proxy enabled for new internet requests.' if settings['enabled'] else
                              'Proxy disabled. New internet requests use a direct connection.')
        self.app.log('Network settings saved. Existing requests finish with their previous connection settings.')

    def test(self):
        if self.testing:
            return
        try:
            settings = self.values()
        except ValueError as error:
            self.status.configure(text=str(error))
            return
        self.test_id += 1
        token = self.test_id
        self.testing = True
        self.test_button.configure(text='Testing…', state='disabled')
        self.status.configure(text='Testing the settings shown above…')
        def finish(message):
            if self.app._closing or not self.winfo_exists():
                return
            self.testing = False
            self.test_button.configure(text='Test connection', state='normal')
            if token == self.test_id:
                self.status.configure(text=message)
        self.app.run_task(lambda: network.test_connection(settings), finish, lambda error: finish(str(error)))
