"""Named light/dark palettes and recoloring for existing CustomTkinter widgets."""

from copy import deepcopy
import json
from pathlib import Path
import tkinter
import sys

PALETTES = {
    'Sage': {
        'background': ('#F3F3ED', '#151D1C'), 'surface': ('#FFFFFF', '#1C2825'),
        'field': ('#F8FAF6', '#17221F'), 'muted': ('#647874', '#98ABA5'),
        'border': ('#DCE4DC', '#344740'), 'text': ('#243B3A', '#E5EEEB'),
        'accent': ('#276B5B', '#438D78'), 'hover': ('#1D574A', '#35735F')},
    'Ocean': {
        'background': ('#EFF4F8', '#141D29'), 'surface': ('#FFFFFF', '#1D2A3A'),
        'field': ('#F6F9FC', '#172333'), 'muted': ('#5D7187', '#9EB2C9'),
        'border': ('#D5E1EE', '#364B63'), 'text': ('#223B55', '#E4EDF7'),
        'accent': ('#285E99', '#3975B6'), 'hover': ('#204C7C', '#2F629A')},
    'Plum': {
        'background': ('#F5F0F7', '#221A29'), 'surface': ('#FFFFFF', '#302438'),
        'field': ('#FBF8FC', '#271D2F'), 'muted': ('#796780', '#B9A4C1'),
        'border': ('#E5D8EA', '#503D5B'), 'text': ('#49324F', '#F0E6F4'),
        'accent': ('#80548F', '#9165A0'), 'hover': ('#694377', '#7B5289')},
    'Amber': {
        'background': ('#F8F3EA', '#241E17'), 'surface': ('#FFFFFF', '#332B21'),
        'field': ('#FCFAF4', '#2A231A'), 'muted': ('#806E51', '#BFAF94'),
        'border': ('#E8DDC8', '#554831'), 'text': ('#51422C', '#F1E8D7'),
        'accent': ('#966322', '#9B6A2C'), 'hover': ('#7A4F19', '#815622')}
}


def palette(name):
    return PALETTES.get(name, PALETTES['Sage'])


def recolor(value, old, new):
    if isinstance(value, (tuple, list)):
        for key, pair in old.items():
            if tuple(value) == pair:
                return new[key]
    elif isinstance(value, str):
        for key, pair in old.items():
            for index, color in enumerate(pair):
                if value.lower() == color.lower():
                    return new[key][index]
    return value


def theme(name):
    baseline = json.loads(Path(__file__).with_name('theme.json').read_text())
    result = deepcopy(baseline)
    platform = 'macOS' if sys.platform == 'darwin' else 'Windows' if sys.platform.startswith('win') else 'Linux'
    result['CTkFont'] = result['CTkFont'][platform]
    for options in result.values():
        for key, value in options.items():
            options[key] = recolor(value, PALETTES['Sage'], palette(name))
    return result


def recolor_widgets(root, old, new):
    options = ('fg_color', 'bg_color', 'top_fg_color', 'border_color', 'text_color',
               'text_color_disabled', 'placeholder_text_color', 'hover_color', 'button_color',
               'button_hover_color', 'progress_color', 'selected_color', 'selected_hover_color')
    for option in options:
        try:
            value = root.cget(option)
        except (ValueError, AttributeError, tkinter.TclError):
            continue
        replacement = recolor(value, old, new)
        if replacement != value:
            root.configure(**{option: replacement})
    for child in root.winfo_children():
        recolor_widgets(child, old, new)
