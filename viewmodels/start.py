# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
View-model for landing page.
"""

import logging
import re
from threading import Thread
import services.meta as m
import services.fileaccess as fa
import services.routines as rou
import services.scheduler as sd
import services.calmgr as cm
from viewmodels import markdown
from datetime import datetime, timedelta
import random


def ctl() -> list[m.view]:
    """ Starting point."""
    forms = []
    _add_intro(forms)
    _add_md(forms)
    _add_cmds(forms)
    _add_tasks(forms)
    _add_agenda(forms)
    _add_help(forms)
    return [m.view("_body", "", forms)]


def _add_intro(forms):
    """ Add intro."""
    #welcome_messages = [
    #    "Welcome",
    #    "Bienvenue",
    #    "Willkommen",
    #    "Bienvenido",
    #    "Benvenuto",
    #    "欢迎",
    #    "Добро пожаловать",
    #    "ようこそ",
    #    "வணக்கம்",
    #    "स्वागत है",
    #    "Selamat Datang",
    #    "שָׁלוֹם",
    #    "환영합니다",
    #    "Välkommen",
    #    "Bem-vindo",
    #    "مرحبا",
    #    "Karibu",
    #    "Sawubona",
    #]
    #random.shuffle(welcome_messages)
    #welcome = '\n'.join(welcome_messages)
    #welcome = ""
    #for i, message in enumerate(welcome_messages):
    #    welcome += f"{message}{'\n' if (i+1) % 3 == 0 else ' '}"
    #date = datetime.now().strftime("%Y-%m-%d")
    #forms.append(m.form(None, None, [
    #    m.label(welcome, "welcome"), m.space(2)], True, False))
    forms.append(m.form(None, None, [m.space(15)], True, False))

def _add_help(forms):
    """ Add help."""
    forms.append(
        m.form(None, 'Help', [
            markdown.for_str("""
# HOMEctlx

## Help 
See README file.

## License 
Copyright (C) 2024 Christian Rauch.
Distributed under terms of the GPL3 license.""", False),
        m.link("/logout", "Logout")
        ], False, True))
    

def _add_tasks(forms):
    tasks = sd.all()
    tasks_str = sorted([f"{t['type']}: {t['desc']}" for t in tasks])
    fields = [m.label(t) for t in tasks_str]
    forms.append(m.form(None, "Tasks", fields, len(tasks) > 0, True, details=f"⚙️ running tasks: {len(tasks)}"))


def _add_md(forms):
    """ Add single markdown."""
    try:
        files_md, _ = fa.list_files(['start/'], True)
        files_md = [f for f in files_md if f.endswith('.md') or f.endswith('.live-md')]
        files_md = sorted(files_md)
        for f in files_md: _load_md(forms, f, False)
    except Exception as e:
        logging.warning(f"Error processing start markdown files: {e}")


def _load_md(forms:list, file:str, open:bool):
    """ Load markdown."""
    try:
        is_live = file.endswith('.live-md')
        meta = fa.read_file_meta_data(['start', file])
        is_editable = is_live and not meta.get('readonly', True)
        md = markdown.for_file('start', file, live=is_editable)
        name = file[:-(8 if is_live else 3)]
        name = re.sub(r'^\d+[_ ]+', '', name)
        name = name.replace('/', ' / ')
        if not isinstance(md, m.space):
            #md.summary = name
            fields = [
                m.applink(
                    f"/files/ctl?dir=start&file={file}", 
                    "edit",
                    f"markdown",
                    "small"),
                md]
            forms.append(m.form(None, name, fields, open, True, 
                                details=f"{'✏️' if is_live else '📝'} start/{file}"))
    except Exception as e: logging.error(f"Error processing '{file}': {e}")


def _add_cmds(forms:list):
    """ Add routines."""
    for key, cmd in rou.get():
        msg = cmd["desc"] if "desc" in cmd else ""
        fields = [
            #m.label(f'command: {key}', 'small'),
            m.label(msg, "", f"exec_result:{key}")
        ]
        forms.append(m.form(None, key.title(), fields, details='⚡ command'))
        if cmd["exec"]["auto"]:
            fields.append(m.autoupdate("start/exec", 0, { "key": key }))
        if cmd["exec"]["manual"]:
            fields.append(m.execute_params("start/exec", params={ "key": key }))


def _add_agenda(forms:list):
    """ Add agenda for today and tomorrow."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=2)  # Today and tomorrow = 2 days range
    
    # Get events for today and tomorrow
    events = cm.get_events(today, tomorrow, days_ahead=2)
    
    # Group events by date
    events_by_date = {}
    for event in events:
        date_key = event.date.strftime('%Y-%m-%d %A')
        if date_key not in events_by_date:
            events_by_date[date_key] = []
        events_by_date[date_key].append(event)
    
    fields = []
    
    if len(events) == 0:
        fields.append(m.label("No events today or tomorrow", "info"))
    else:
        # List events grouped by date
        for date_key in sorted(events_by_date.keys()):
            date_events = events_by_date[date_key]
            
            fields.append(m.label(f"{date_key}", "title-2"))
            
            for event in date_events:
                recurring_text = ""
                if event.recurring:
                    recurring_text = f"[{event.recurring}"
                    if event.end_date:
                        recurring_text += f",end:{event.end_date.strftime('%Y-%m-%d')}"
                    recurring_text += "] "
                source_text = f"[{event.source.replace('/', ' > ')}]"
                # Replace newlines with backslash for single-line display
                display_description = event.description.replace('\n', ' \\ ')
                
                event_table = m.table(rows=[
                    [m.label(display_description, "")],
                    [m.label(recurring_text + source_text, "small inactive")]
                ])
                fields.append(event_table)
    
    # Open if there are events
    is_open = len(events) > 0
    
    forms.append(m.form(None, "Agenda", fields, is_open, True, 
                        details=f"📅 upcoming events: {len(events)}"))


def exec(key:str):
    """ Execute routines."""
    msg = rou.exec(key)
    return [m.label(msg, "", f"exec_result:{key}")]