# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
View-model meta data to describe the UI.
"""

from dataclasses import dataclass, field
from typing import Iterator
from services.lightstates import State


class uielement:
    key:str
    desc:str=None
    style:str=''
    def type(self): return type(self).__name__
    def haskey(self): return hasattr(self, 'key') and self.key not in [None, '']


@dataclass
class view(uielement):
    key:str
    name:str
    forms:list


@dataclass
class form(uielement):
    key:str
    name:str
    fields:list
    open:bool=False
    table:bool=True
    style:str=''
    details:str=''


@dataclass
class header(uielement):
    fields:list
    name:str=None
    key:str="_header"
    style:str=''


@dataclass
class execute(uielement):
    func:str
    text:str="execute"
    important:bool=False
    key:str=None
    confirm:str=None
    style:str=''


@dataclass
class execute_params(uielement):
    func:str
    text:str="execute"
    params:dict=None
    important:bool=False
    key:str=None
    confirm:str=None
    style:str=''


@dataclass
class autoupdate(uielement):
    func:str
    delay:int=1000
    params:dict=None


@dataclass
class choice(uielement):
    value:str
    text:str=None
    important:bool=False
    def makelist(items:Iterator, important:bool=False) -> list: 
        return list(map(lambda i: choice(i, important=important), items))


@dataclass
class triggers(uielement):
    func:str
    param:str
    values:list[choice]
    desc:str=None
    confirm:str=None


@dataclass
class pager(uielement):
    func:str
    param:str
    st_idx:int
    page_sz:int
    all_sz:int
    container:str
    focus:bool=False
    params:dict=None
    #params:dict=field(default_factory=dict)


@dataclass
class show(uielement):
    func:str
    param:str
    idx:int
    size:int
    item:str
    back:str
    link:str


@dataclass
class path(uielement):
    func:str
    param:str
    values:list[choice]
    desc:str=None


@dataclass
class input(uielement):
    param:str


@dataclass
class hidden(input):
    param:str
    value:str


@dataclass
class integer(input):
    param:str
    value:int
    desc:str=""


@dataclass
class time(input):
    param:str
    value:str
    desc:str


@dataclass
class text(input):
    param:str
    text:str
    desc:str=None
    key:str=""


@dataclass
class text_big(input):
    param:str
    text:str
    desc:str=None


@dataclass
class text_ro(uielement):
    text:str
    desc:str=None


@dataclass
class text_big_ro(uielement):
    key:str
    text:str
    desc:str=None


@dataclass
class select(uielement):
    param:str
    values:list[choice]
    default:choice=None
    desc:str=None
    func:str=None


@dataclass
class select_many(uielement):
    param:str
    values:list[choice]
    defaults:list[choice]
    desc:str=None


@dataclass
class upload(uielement):
    param:str
    desc:str=None


@dataclass
class download(uielement):
    file:str
    text:str="download"
    desc:str=None


@dataclass
class media(uielement):
    file:str
    format:str


@dataclass
class link(uielement):
    link:str
    text:str
    style:str=''


@dataclass
class applink(uielement):
    link:str
    text:str
    prefix:str='open'
    style:str=''
    postfix:str=''


@dataclass
class embed(uielement):
    link:str
    text:str
    style:str=''
    height:int=380


@dataclass
class actions(uielement):
    items:list


@dataclass
class section(uielement):
    content:list
    key:str=None


@dataclass
class collapsible(uielement):
    summary:str
    content:list
    open:bool=False


@dataclass
class markdown(uielement):
    content:list
    recess:bool=True
    summary:str=None
    path:str=None
    live:bool=False
    key:str=None


@dataclass
class title(uielement):
    text:str
    order:int=1
    line_idx:int=None
    raw:str=None


@dataclass
class label(uielement):
    text:str
    style:str=''
    key:str=None
    details:str=''
    line_idx:int=None
    data:str=None
    raw:str=None


@dataclass
class labelline(uielement):
    texts:list[str]
    styles:list[str]=field(default_factory=list)
    key:str=None


@dataclass
class space(uielement):
    rows:int


@dataclass
class dir(uielement):
    func:str
    dir_parent:str
    dir:str
    readonly:bool
    files:int
    def path(self) -> str:
        if self.dir == '..': return self.dir_parent
        return f'{self.dir_parent}/{self.dir}'


@dataclass
class file(uielement):
    func:str
    dir:str
    file:str
    readonly:bool
    link:str


@dataclass
class placeholder(uielement):
    key:str


@dataclass
class error(uielement):
    text:str=None
    key:str="_error"


@dataclass
class back(uielement):
    """ Sentinel that tells the client to navigate back."""
    key:str="_back"


@dataclass
class light(uielement):
    func:str
    state:State
    readonly:bool=False


@dataclass
class menu(uielement):
    pass


@dataclass
class table(uielement):
    rows:list[list[uielement]]
    headers:list[str]=None
    style:str=''
    key:str=None


@dataclass
class notification(uielement):
    text:str
    key:str='_notification'