# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
Application entry point.
"""

import json
import logging
import secrets
from datetime import timedelta
from flask import Flask, redirect, request
from flask_socketio import SocketIO

import services.fileaccess as fa
import services.dbaccess as dba
import services.lightctlwrapper as lw
import services.ambinterpreter as ami
import services.routines as rou
import services.scheduler as sch
import services.authservice as auth
from services.reqhandler import cmdex_pb
import services.reqhandler as reqhandler
import services.soundctl as soundctl


app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
# WebSocket connections use Flask's session management
# Configure with longer timeouts and ping settings to reduce connection churn
socketio = SocketIO(
    app, 
    cors_allowed_origins=[], 
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1000 * 1024 * 1024,  # 1000 MB, supports large file uploads sent as base64
    logger=False,
    engineio_logger=False
)
log = logging.getLogger(__file__)


def create_app(app):
    """ Initialize components, set dependencies (Inversion of Control)."""
    
    with open("config.json", "r") as config_file:
        config = json.load(config_file)
        app.config.update(config)
    
    fa.init(app.config["share_dir"])
    soundctl.init(app.config.get("spotify", {}))

    log.info("System initializing.")

    logging.basicConfig(
        level=logging.INFO, 
        format="%(asctime)s [%(levelname)s] [%(module)s.%(funcName)s:%(lineno)d]: %(message)s",
        handlers=[
            logging.FileHandler(fa.share_path(["temp", "logs"]), mode="w"),
            logging.StreamHandler()
        ])
    
    dba.init()
    lw.init(app.config["lightctl_exec"])
    sch.init(dba)
    ami.init(fa, dba, lw)
    rou.init(app.config["routines"])
    
    app.register_blueprint(cmdex_pb)
    
    # Register WebSocket handlers
    reqhandler.socketio = socketio
    
    @socketio.on('connect')
    def handle_connect(data = None):
        """ Verify authentication on WebSocket connection."""
        if not auth.is_authenticated():
            log.warning("Unauthorized WebSocket connection attempt")
            return False  # Reject connection
        #log.info(f"WebSocket connection established for user: {auth.get_current_user().get('uname', 'unknown')}")
        return True
    
    @socketio.on('disconnect')
    def handle_disconnect(data = None):
        """ Handle WebSocket disconnection."""
        #log.info("WebSocket disconnected")
    
    @socketio.on('execute')
    def handle_execute(data = None):
        """ Handle WebSocket execute events."""
        # Double-check authentication for each request
        if not auth.is_authenticated():
            log.warning("Unauthorized execute attempt via WebSocket")
            return
        reqhandler.reqhandler.handle_execute(data)

    @socketio.on('join_live')
    def handle_join_live(data = None):
        """ Handle joining a live-md room."""
        if not auth.is_authenticated(): return
        reqhandler.reqhandler.handle_join_live(data)

    @socketio.on('leave_live')
    def handle_leave_live(data = None):
        """ Handle leaving a live-md room."""
        if not auth.is_authenticated(): return
        reqhandler.reqhandler.handle_leave_live(data)

    @app.route('/sound/login')
    def sound_login():
        """Redirect user to Spotify OAuth authorization page."""
        return redirect(soundctl.login_url())

    @app.route('/sound/callback')
    def sound_callback():
        """Handle Spotify OAuth callback, exchange code for tokens."""
        code = request.args.get('code', '')
        if code:
            soundctl.exchange_code(code)
        return redirect('/sound/ctl')

    @app.route('/')
    def index(): return redirect('start/ctl')
    
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """ Handle login page and authentication."""
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            remember = request.form.get('remember') == 'yes'
            
            success, result = auth.handle_login(username, password, remember)
            if success:
                return result  # redirect response
            else:
                return auth.render_login_page(error=result)
        
        # GET request - show login page
        return auth.render_login_page()
    
    @app.route('/logout')
    def logout():
        """ Handle logout."""
        return auth.handle_logout()

    log.warning("System initialized.")

    return app


@app.teardown_request
def after_request(exception):
    """ Free resources after the request."""
    dba.close_cached()
    if exception != None: log.error(exception)


@app.before_request
def before_request():
    """ Acquire resources before the request and check authentication."""
    dba.connect_cached()
    
    # Socket.IO requests need special handling - authentication is checked
    # at the WebSocket connection level, not at the HTTP request level
    if request.path.startswith('/socket.io/'):
        if not auth.is_authenticated():
            return redirect('/login')
        return None
    
    return auth.require_authentication()


create_app(app)

if __name__ == "__main__": 
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    socketio.run(app, debug=debug_mode)