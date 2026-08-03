# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
Offers create, read, update, delete and more for the file system.
"""

from ast import Lambda
import logging
import os
from pathlib import Path
import shutil
import threading
import datetime
import random
import re
import sys
import zipfile

from flask import session
import services.dbaccess as dba


log = logging.getLogger(__file__)
mutex = threading.RLock()
share_dir = None


def init(base_dir):
    """ Sets the base directory."""
    global share_dir
    share_dir = os.path.realpath(base_dir)
    log.info(f"Share: {share_dir}")


def share_path(parts:list[str]) -> str:
    """ Gets the share path (editable). """
    return absolute_path(share_dir, parts)


def absolute_path(base_dir, parts:list[str]) -> str:
    """ Checks whether the path can be accessed. 
    Directory traversal attacks are prevented."""
    path = sanitize([base_dir, *parts])
    path = os.path.realpath(path)
    if os.path.commonprefix((path, base_dir)) != base_dir:
        log_action(f"Illegal path requested: {path}", True)
        raise Exception("File must be in valid directory")
    return path


def sanitize(parts:list[str]) -> str:
    """ Forms the path from the parts."""
    def clean(p):
        while p.startswith('/') or p.endswith('/'):
            p = p.strip('/')
        return p
    parts = [clean(p) for p in parts]
    path = '/'.join(parts)
    while path.endswith(".."):
        parts = path.split('/')[:-2]
        path = '/'.join(parts)
    return f'/{path}'


def list_files(path:list[str], include_subdirs=False) \
    -> tuple[list[str], list[str]]:
    """ Gets all files (no files with a dot prefix)."""
    return _list_files(Path(share_path(path)), include_subdirs)


def _list_files(path:Path, include_subdirs=False) \
    -> tuple[list[str], list[str]]:
    """ Gets all files (no files with a dot prefix)."""
    files = list()
    dirs = list()
    with mutex:
        for entry in path.iterdir():
            if entry.name.startswith("."): continue
            if entry.is_dir():
                dirs.append(entry.name)
                if include_subdirs:
                    sub_files, _ = _list_files(entry, include_subdirs)
                    sub_files = [f"{entry.name}/{sub_file}" for sub_file in sub_files]
                    files.extend(sub_files)
            elif entry.is_file():
                files.append(entry.name)
    return sorted(files), sorted(dirs)


def clean_lines(content:str) -> list[str]:
    """ Returns the content as cleaned lines."""
    return [l.strip() for l in content.split("\n") if not l.isspace() and l != ""] 


def create_file(path:list[str], content):
    """ Creates a file."""
    if   isinstance(content, str):   mode = "w"
    elif isinstance(content, bytes): mode = "wb"
    else: 
        log_action(f"Illegal content type: {path}", True)
        raise Exception("Content must be a string or bytes.")
    with mutex, open(share_path(path), mode) as f: f.write(content)
    log_action(f"File created: {path}.")


def read_file(path:list[str], default:str="") -> str:
    """ Reads a file."""
    try:
        with mutex, open(share_path(path), "r") as f: return f.read()
    except Exception as e:
        log_action(f"File '{path}' could not be read: {e}", True)
        return default


def read_file_meta_data(path:list[str]):
    """ Reads the meta data of a file."""
    meta = { 
        "readonly": True,
        "is_text":  False,
        "is_image": False,
        "is_video": False,
        "is_pdf":   False,
        "is_markdown": False,
        "is_live": False,
        }
    file = share_path(path)
    with mutex:
        bytes = os.path.getsize(file)
        meta["size"] = bytes
        meta["changed"] = datetime.datetime.fromtimestamp(
            os.path.getmtime(file))
        if os.access(file, os.W_OK): meta["readonly"] = False
        if path[-1].find(".") < 0 or \
            path[-1].split('.')[-1] in ["txt", "json", "yaml", "log", "calx"]:
            if bytes < 10000 and read_file(path).count("\n") < 1000:
                meta["is_text"] = True
        elif path[-1].find(".") > 0:
            extension = path[-1].split('.')[-1].lower()
            if extension in \
                ["jpg", "jpeg", "png", "gif", "bmp", "svg", 
                "tiff", "tif", "webp", "heif", "heic"]:
                meta["is_image"] = True
            elif extension in \
                ["mp4", "mov", "avi", "wmv", "mkv", "flv",
                "webm","m4v", "mpeg", "mpg", "3gp", "3g2"]:
                meta["is_video"] = True
            elif extension == "md":       meta["is_markdown"] = True
            elif extension == "live-md": meta["is_live"] = True
            elif extension == "pdf":      meta["is_pdf"] = True
    return meta


def read_directory_meta_data(path: list[str]):
    """Reads the meta data of a directory."""
    meta = { 
        "readonly": True,
        "files":  0
    }
    dir_path = share_path(path)
    with mutex:
        if os.access(dir_path, os.W_OK):
            meta["readonly"] = False
        try:
            files = os.listdir(dir_path)
            meta["files"] = len(files)
        except OSError as e:
            meta["files"] = 0
            log_action(f"Directory '{path}' could not be read: {e}", True)

    return meta


def update_file(path:list[str], content:str, overwrite:bool):
    """ Updates a file (overwrite or append)."""
    mode = "w" if overwrite else "a"
    with mutex, open(share_path(path), mode) as f: f.write(content)
    log_action(f"File updated: {path}.")


def update_line(path:list[str], line_idx:int, new_content:str):
    """ Replaces a single line in a file by zero-based index."""
    with mutex:
        lines = read_file(path).split("\n")
        lines[int(line_idx)] = new_content
        update_file(path, "\n".join(lines), True)


def append_line(path:list[str], new_content:str):
    """ Appends a new line to a file."""
    with mutex:
        content = read_file(path)
        sep = "" if content.endswith("\n") else "\n"
        update_file(path, content + sep + new_content + "\n", True)


def clean_file(path:list[str], remove:Lambda):
    """ Removes lines matching the lambda."""
    with mutex: 
        lines = clean_lines(read_file(path))
        lines_clean =  [l for l in lines if not remove(l)]
        content = "\n".join(lines_clean)
        content = content + "\n"
        update_file(path, content, True)


def move_file(path:list[str], path_new:list[str]):
    """ Moves a file."""
    assert_not_essential(path)
    assert_not_essential(path_new)
    old = share_path(path)
    new = share_path(path_new)
    with mutex: os.rename(old, new)
    log_action(f"File moved: {path} -> {path_new}.")


def delete_file(path:list[str]):
    """ Deletes a file."""
    assert_not_essential(path)
    with mutex: os.remove(share_path(path))
    log_action(f"File deleted: {path}.")


def create_archive(path:list[str]) -> str:
    """ Create an archive and returns the path."""
    path_dir = share_path(path)
    # compose archive name: time stamp + random number
    time = f"{datetime.datetime.now():%Y%m%d%H%M%S}"
    number = random.randint(0, sys.maxsize)
    dir_name = re.sub(r"[^\w_. -]", "_", path)
    archive_file = f"archive-{dir_name}-{time}-{number}.zip"
    # archive files are stored in the root directory
    path_archive = os.path.join(share_dir, "temp", archive_file)
    # iterate over files and add them to archive
    with mutex:
        with zipfile.ZipFile(path_archive,"w") as archive:
            for root, dirs, files in os.walk(path_dir):
                for file in files:
                    if file.startswith("."): continue
                    filepath = os.path.join(root, file)
                    filepath_archive = filepath[path_dir.__str__().__len__():]
                    archive.write(filepath, filepath_archive)
    path_archive_relative = path_archive[len(share_dir)+1:]
    log_action(f"Archive created: {path_archive_relative}.")
    return path_archive_relative


def create_directory(path:list[str]):
    """ Creates a directory."""
    with mutex: os.mkdir(share_path(path))
    log_action(f"Directory created: {path}.")


def delete_directory(path:list[str]):
    """ Deletes a directory."""
    assert_not_essential(path)
    with mutex: shutil.rmtree(share_path(path))
    log_action(f"Directory deleted: {path}.")


def move_directory(path:list[str], path_new:list[str]):
    """ Moves a directory."""
    assert_not_essential(path)
    assert_not_essential(path_new)
    old = share_path(path)
    new = share_path(path_new)
    with mutex: shutil.move(old, new)
    log_action(f"Directory moved: {path} -> {path_new}.")


def is_essential(path:list[str]):
    """ Checks whether a path can be edited."""
    target = share_path(path)
    for p in [
            [""],
            ["calendar"],
            ["calendar", "global"],
            ["documents"],
            ["documents", "templates"],
            ["ambients"],
            ["ambients", "macros"],
            ["temp"],
            ["temp", "logs"],
        ]:
        critical = share_path(p)
        if target == critical: return True
    return False


def assert_not_essential(path:list[str]):
    """ Checks whether a path can be edited."""
    if is_essential(path):
        log_action(f"Access denied to '{path}'", True)
        raise Exception(f"Access denied to '{path}'")


def log_action(msg:str, is_error:bool = False):
    """ Logs an action."""
    msg_user = f'[user:{session["uname"]}] {msg}'
    if is_error: log.error(msg_user)
    else:        log.info(msg_user)
    dba.update_user_history(session['uname'], msg)