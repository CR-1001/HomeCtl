# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
View-model for markdown.
"""

import logging
import re
import services.meta as m
import services.fileaccess as fa

from typing import Generator

def _replace_symbols(text: str) -> str:
    """ Replace symbols. """
    text = re.sub(r'\[ \]', '☐', text)
    text = re.sub(r'\[x\]', '☑', text, flags=re.IGNORECASE)
    text = re.sub(r'<->', '↔', text)
    text = re.sub(r'->', '→', text)
    text = re.sub(r'<-', '←', text)
    text = re.sub(r'(?<!-)---(?!-)', '—', text)
    text = re.sub(r'(?<!-)--(?!-)', '–', text)
    text = re.sub(r'\.\.\.', '…', text)
    return text

def for_str(content: str, recess: bool = True, live: bool = False) -> m.markdown:
    """ Convert a markdown string to a uielement. """

    sectionsx = [s for s in re.split(r'(?m)(?=^# )', content.strip()) if s.strip()]
    sections = list()

    # For live mode: track each line's index in the original file.
    # Use the original (un-stripped) lines so cursor matching is exact.
    all_lines = content.split("\n") if live else []
    line_cursor = 0

    for s in sectionsx:

        fields = []
        lines = s.strip().split("\n")

        for l in lines:

            # Find this line's position in the original file
            live_idx = None
            if live and l.strip() != '':
                while line_cursor < len(all_lines) and all_lines[line_cursor].strip() != l.strip():
                    line_cursor += 1
                if line_cursor < len(all_lines):
                    live_idx = line_cursor
                    line_cursor += 1

            if l.startswith("#"):
                order = 0
                for char in l:
                    if char == '#': order += 1
                    else: break
                t = m.title(l[order:].strip(), order)
                if live_idx is not None:
                    t.line_idx = live_idx
                    t.raw = l
                fields.append(t)
            else:
                links = re.findall(r'\[(.*?)\]\((.*?)\)', l)
                prev_idx = 0
                for link in links:
                    replace = f"[{link[0]}]({link[1]})"
                    index = l.find(replace, prev_idx)
                    if index != -1:
                        if prev_idx != index:
                            lbl = m.label(_replace_symbols(l[prev_idx:index]))
                            if live_idx is not None:
                                lbl.line_idx = live_idx
                                lbl.raw = l
                            fields.append(lbl)
                        src = link[1].strip()
                        if src.startswith('embed:'):
                            fields.append(m.embed(src[6:], link[0].strip()))
                        else:
                            fields.append(m.link(src, link[0].strip()))
                        prev_idx = index + len(replace)
                
                if prev_idx < len(l):
                    lbl = m.label(_replace_symbols(l[prev_idx:]))
                    if live_idx is not None:
                        lbl.line_idx = live_idx
                        lbl.raw = l
                    fields.append(lbl)

            fields.append(m.space(1))
        fields.append(m.space(1))

        sections.append(m.section(fields))
    
    return m.markdown(sections, recess)


def for_file(dir:str, file:str, recess:bool=True, live:bool=False) -> m.uielement:
    """ Markdown fields from a file. """
    try:
        content = fa.read_file([dir, file])
        md = for_str(content, recess, live)
        if live:
            md.live = True
            md.path = fa.sanitize([dir, file])
            md.key = 'livemd_' + re.sub(r'[^a-zA-Z0-9-]', '_', md.path).strip('_')
        return md
    
    except Exception as e:
        logging.warning(f"File '{file}' in '{dir}' cannot be interpreted: {e}")
        return m.space(1)
