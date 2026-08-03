# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
The request handler receives requests and passes parameters to the view-models. The UI meta-data returned is used to render HTML.
"""

from collections.abc import Iterable
import inspect
import logging
from flask import Blueprint, render_template, send_from_directory, request, jsonify
from flask_socketio import emit, join_room, leave_room
import services.meta as m
import services.fileaccess as fa
import services.state as state
from viewmodels import files, start, alarms, ambients, lights, telemetry, calendar, sound

log = logging.getLogger(__name__)


cmdex_pb = Blueprint("cmd", __name__)

# Global socketio instance (will be set by app.py)
socketio = None


class reqhandler:
    """ Renders the view models."""

    modules = {}
    for m in [start, files, alarms, ambients, lights, telemetry, calendar, sound]:
        modules[m.__name__.replace('viewmodels.', '')] = m

    @cmdex_pb.route("/<vm>/ctl")
    def control(vm:str):
        """ Starting point."""
        return render_template("control.html", vm=vm)
    

    @staticmethod
    def handle_execute(data):
        """ WebSocket handler for execute events."""
        # Validate input data structure
        if not isinstance(data, dict):
            emit('response', {"_error": render_template("field.html", field=m.error("Invalid request format"))})
            return
        
        vm = data.get('vm')
        func = data.get('func')
        args = data.get('args', {})
        
        # Validate required fields
        if not vm or not isinstance(vm, str):
            emit('response', {"_error": render_template("field.html", field=m.error("Invalid view model"))})
            return
        
        # Security: Only allow whitelisted view models
        if vm not in reqhandler.modules:
            emit('response', {"_error": render_template("field.html", field=m.error("Unknown view model"))})
            return
        
        # Security: Validate func is a string
        if func is not None and not isinstance(func, str):
            emit('response', {"_error": render_template("field.html", field=m.error("Invalid function name"))})
            return
        
        if not isinstance(args, dict):
            emit('response', {"_error": render_template("field.html", field=m.error("Invalid arguments"))})
            return
        
        payload = reqhandler.exec(vm, func, args)
        emit('response', payload)

        # Broadcast live-md line updates to all other users viewing the same file
        if vm == 'files' and func in ('update_line', 'append_line') and isinstance(args, dict):
            live_path = args.get('live_path', '')
            if live_path:
                # Broadcast the same content keys that were sent to the saving user.
                # Skip _error and None-keyed entries.
                broadcast = {k: v for k, v in payload.items()
                             if k not in (None, '_error')}
                if broadcast:
                    socketio.emit(
                        'response', broadcast,
                        to=f"live:{live_path}", skip_sid=request.sid)

        # Broadcast full-file saves (update_file / update_file_back) to live-md viewers
        if vm == 'files' and func in ('update_file', 'update_file_back') and isinstance(args, dict):
            file = args.get('file', '')
            if file:
                curr_dir = state.get('files.dir', '/')
                live_path = fa.sanitize([curr_dir, file])
                file_meta = fa.read_file_meta_data([curr_dir, file])
                if file_meta.get('is_live'):
                    md = files.for_file_live(curr_dir, file, file_meta)
                    if md is not None:
                        html = render_template('field.html', field=md)
                        socketio.emit(
                            'response', {md.key: html},
                            to=f"live:{live_path}", skip_sid=request.sid)
    

    @staticmethod
    def exec(vm:str, func:str, args:dict):
        """ Executes the command."""
        try:
            if func in ['', None, 'undefined']: func = 'ctl'
            
            # Security: Prevent access to private/dunder methods
            if func.startswith('_'):
                raise AttributeError(f"Access to private method '{func}' denied")
            
            method = getattr(reqhandler.modules[vm], func)
            if not callable(method):
                raise AttributeError(f"'{func}' is not a callable method")
            
            sig = inspect.signature(method)
            accepted_params = sig.parameters.keys()
            # Filter to only accepted params and exclude empty string values
            # (empty strings from form inputs shouldn't override default values;
            # exception: update_line's 'content' param may legitimately be empty)
            allow_empty = {'content'} if func in ('update_line', 'append_line') else set()
            filtered_args = {k: v for k, v in args.items() \
                if k in accepted_params and (v not in ['', None] or k in allow_empty)}
            elements = method(**filtered_args)
            if not isinstance(elements, Iterable): elements = [elements]
            
            payload = {}
            for e in elements:
                if e.type() == "back":
                    payload["_back"] = "1"
                elif e.type() == "view":
                    html = render_template(f"view.html", view=e)
                elif e.type() in ["form", "header"]:
                    html = render_template(f"form.html", form=e)
                else:
                    html = render_template(f"field.html", field=e)
                payload[e.key] = html
            if not "_error" in payload:
                payload["_error"] = render_template(\
                    f"field.html", field=m.error())
        
        except AttributeError as e:
            # Log the actual error but show generic message to user
            log.error(f"AttributeError in exec: {str(e)}")
            payload = {"_error": render_template(\
                "field.html", field=m.error("Invalid command or permission denied")) }
        except Exception as e:
            # Log detailed error but show generic message to user for security
            log.error(f"Error executing command: {str(e)}")
            payload = {"_error": render_template(\
                "field.html", field=m.error("An error occurred while processing your request")) }
            
        return payload
    

    @cmdex_pb.route("/files/upload/check", methods=["POST"])
    def check_upload_conflicts():
        """Pre-flight endpoint: returns original filenames whose resolved names already exist."""
        data   = request.get_json(silent=True) or {}
        names  = data.get('names', [])
        rename = data.get('rename', '')
        return jsonify({'skip_originals': files.check_upload_conflicts(names, rename)})

    @cmdex_pb.route("/files/upload", methods=["POST"])
    def upload_file_http():
        """HTTP multipart upload endpoint — used by the XHR progress uploader."""
        upload_list = request.files.getlist('upload')
        rename = request.form.get('rename', '')
        try:
            elements = files.upload_file_http(upload_list, rename)
            if not isinstance(elements, Iterable): elements = [elements]
            payload = {}
            for e in elements:
                if e.type() == "back":
                    payload["_back"] = "1"
                elif e.type() == "view":
                    html = render_template("view.html", view=e)
                elif e.type() in ["form", "header"]:
                    html = render_template("form.html", form=e)
                else:
                    html = render_template("field.html", field=e)
                if e.type() != "back":
                    payload[e.key] = html
            if "_error" not in payload:
                payload["_error"] = render_template("field.html", field=m.error())
        except Exception as e:
            log.error(f'File upload error: {e}')
            payload = {'_error': render_template('field.html', field=m.error('Upload failed'))}
        return jsonify(payload)

    @cmdex_pb.route("/files/share/<path:file>")
    def get_file(file:str):
        """ Sends the file."""
        # Security: Prevent path traversal attacks
        from werkzeug.security import safe_join
        from flask import abort
        
        safe_path = safe_join(fa.share_dir, file)
        if safe_path is None or not safe_path.startswith(fa.share_dir):
            abort(403)
        
        return send_from_directory(fa.share_dir, file)