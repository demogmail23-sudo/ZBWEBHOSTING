import os
import json
import re
import subprocess
import psutil
import socket
import sys
import hashlib
import secrets
import shutil
import zipfile
import time
import platform
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, send_from_directory, request, jsonify, session, redirect, url_for, make_response
from flask_cors import CORS

# ============== CONFIGURATION ==============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "USERS")
BACKUP_DIR = os.path.join(BASE_DIR, "BACKUPS")
TEMPLATES_DIR = os.path.join(BASE_DIR, "TEMPLATES")
SUBDOMAINS_FILE = os.path.join(BASE_DIR, "subdomains.json")

for dir_path in [USERS_DIR, BACKUP_DIR, TEMPLATES_DIR]:
    os.makedirs(dir_path, exist_ok=True)

app = Flask(__name__, static_folder=BASE_DIR)
app.secret_key = secrets.token_hex(32)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
CORS(app, supports_credentials=True)

# Admin credentials
ADMIN_USERNAME = "ZAINU121"
ADMIN_PASSWORD = "8057558009"
USERS_FILE = os.path.join(BASE_DIR, "users.json")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# ============== INITIALIZE FILES ==============
def init_users_db():
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            admin_data = {
                ADMIN_USERNAME: {
                    "password": hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest(),
                    "email": "admin@zainu.host",
                    "created_at": datetime.now().isoformat(),
                    "last_login": None,
                    "is_admin": True,
                    "storage_quota": 10240,
                    "storage_used": 0,
                    "api_keys": [],
                    "servers": [],
                    "subdomains": [],
                    "activity_logs": [],
                    "settings": {}
                }
            }
            json.dump(admin_data, f, indent=2)

def init_settings():
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "maintenance_mode": False,
                "announcement": "Welcome to ZAINU HOST! 🚀",
                "referral_bonus": 100,
                "max_servers_per_user": 10,
                "site_name": "ZAINU HOST",
                "site_description": "Professional Hosting Platform"
            }, f, indent=2)

def init_subdomains():
    if not os.path.exists(SUBDOMAINS_FILE):
        with open(SUBDOMAINS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2)

init_users_db()
init_settings()
init_subdomains()

# ============== HELPER FUNCTIONS ==============
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_activity(username, action, details="", ip=None):
    if ip is None and request:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr) or request.remote_addr
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if username in users:
        if "activity_logs" not in users[username]:
            users[username]["activity_logs"] = []
        
        users[username]["activity_logs"].insert(0, {
            "action": action,
            "details": details,
            "ip": ip,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 200 logs
        users[username]["activity_logs"] = users[username]["activity_logs"][:200]
        
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

def get_user_servers_dir(username=None):
    if username is None:
        username = session.get('username')
    return os.path.join(USERS_DIR, username, "SERVERS")

def sanitize_name(name):
    if not name: return ""
    name = name.strip()
    name = re.sub(r"\s+", "-", name)
    name = re.sub(r"[^A-Za-z0-9\-\_\.]", "", name)
    return name[:200]

def calculate_storage_used(username):
    user_dir = os.path.join(USERS_DIR, username)
    total = 0
    if os.path.exists(user_dir):
        for root, dirs, files in os.walk(user_dir):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except:
                    pass
    return total // (1024 * 1024)

def update_storage_used(username):
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    if username in users:
        users[username]["storage_used"] = calculate_storage_used(username)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)

# ============== DECORATORS ==============
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        
        if not users.get(session['username'], {}).get("is_admin", False):
            return jsonify({"success": False, "message": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

# ============== ROUTES ==============
@app.route("/")
def home():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)
    
    if settings.get("maintenance_mode", False):
        return "<h1>🔧 Maintenance Mode</h1><p>Website is under maintenance. Please check back later.</p>"
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if users.get(session['username'], {}).get("is_admin", False):
        return send_from_directory(BASE_DIR, "admin_panel.html")
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/login")
def login_page():
    if 'username' in session:
        return redirect(url_for('home'))
    return send_from_directory(BASE_DIR, "login.html")

@app.route("/api/current_user")
def api_current_user():
    if 'username' in session:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        
        user_data = users.get(session['username'], {})
        
        return jsonify({
            "success": True,
            "username": session['username'],
            "is_admin": user_data.get("is_admin", False),
            "email": user_data.get("email", ""),
            "storage_quota": user_data.get("storage_quota", 500),
            "storage_used": user_data.get("storage_used", 0),
            "created_at": user_data.get("created_at"),
            "api_keys_count": len(user_data.get("api_keys", [])),
            "subdomains_count": len(user_data.get("subdomains", []))
        })
    return jsonify({"success": False})

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    remember_me = data.get("remember_me", False)
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if username not in users:
        return jsonify({"success": False, "message": "User not found"})
    
    if users[username]["password"] != hash_password(password):
        return jsonify({"success": False, "message": "Incorrect password"})
    
    session['username'] = username
    session.permanent = remember_me
    users[username]["last_login"] = datetime.now().isoformat()
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    log_activity(username, "login", "User logged in successfully")
    
    return jsonify({
        "success": True,
        "is_admin": users[username].get("is_admin", False),
        "username": username
    })

@app.route("/api/logout", methods=["POST"])
def api_logout():
    if 'username' in session:
        log_activity(session['username'], "logout", "User logged out")
    session.pop('username', None)
    return jsonify({"success": True})

@app.route("/api/register", methods=["POST"])
@admin_required
def api_register():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    email = data.get("email", "").strip()
    quota = int(data.get("quota", 500))
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if username in users:
        return jsonify({"success": False, "message": "Username already exists"})
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters"})
    
    if email and any(u.get("email") == email for u in users.values()):
        return jsonify({"success": False, "message": "Email already used"})
    
    users[username] = {
        "password": hash_password(password),
        "email": email,
        "created_at": datetime.now().isoformat(),
        "last_login": None,
        "is_admin": False,
        "storage_quota": quota,
        "storage_used": 0,
        "servers": [],
        "api_keys": [],
        "subdomains": [],
        "activity_logs": []
    }
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    user_dir = os.path.join(USERS_DIR, username)
    os.makedirs(user_dir, exist_ok=True)
    os.makedirs(os.path.join(user_dir, "SERVERS"), exist_ok=True)
    
    log_activity(session['username'], "create_user", f"Created user: {username}")
    
    return jsonify({"success": True, "message": "User created successfully"})

@app.route("/api/user/update", methods=["POST"])
@login_required
def update_user():
    data = request.get_json()
    email = data.get("email", "")
    new_password = data.get("password", "")
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    username = session['username']
    
    if email:
        users[username]["email"] = email
    
    if new_password and len(new_password) >= 6:
        users[username]["password"] = hash_password(new_password)
        log_activity(username, "change_password", "Password changed")
    elif new_password:
        return jsonify({"success": False, "message": "Password must be 6+ characters"})
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    log_activity(username, "update_profile", f"Updated email: {email}")
    
    return jsonify({"success": True, "message": "Profile updated"})

@app.route("/api/user/stats")
@login_required
def user_stats():
    username = session['username']
    update_storage_used(username)
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    user_data = users.get(username, {})
    servers_count = len(user_data.get("servers", []))
    api_keys_count = len(user_data.get("api_keys", []))
    subdomains_count = len(user_data.get("subdomains", []))
    
    return jsonify({
        "success": True,
        "storage_used": user_data.get("storage_used", 0),
        "storage_quota": user_data.get("storage_quota", 500),
        "servers_count": servers_count,
        "api_keys_count": api_keys_count,
        "subdomains_count": subdomains_count
    })

# ============== ADMIN ROUTES ==============
@app.route("/api/admin/users", methods=["GET"])
@admin_required
def get_all_users():
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    user_list = []
    for username, data in users.items():
        if username != ADMIN_USERNAME:
            user_list.append({
                "username": username,
                "email": data.get("email", ""),
                "created_at": data.get("created_at"),
                "last_login": data.get("last_login"),
                "storage_quota": data.get("storage_quota", 500),
                "storage_used": data.get("storage_used", 0),
                "servers_count": len(data.get("servers", [])),
                "api_keys_count": len(data.get("api_keys", [])),
                "subdomains_count": len(data.get("subdomains", []))
            })
    
    return jsonify({"success": True, "users": user_list})

@app.route("/api/admin/delete-user", methods=["POST"])
@admin_required
def delete_user_admin():
    data = request.get_json()
    username = data.get("username", "").strip()
    
    if username == ADMIN_USERNAME:
        return jsonify({"success": False, "message": "Cannot delete main admin"})
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if username not in users:
        return jsonify({"success": False, "message": "User not found"})
    
    del users[username]
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    user_dir = os.path.join(USERS_DIR, username)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
    
    log_activity(session['username'], "delete_user", f"Deleted user: {username}")
    
    return jsonify({"success": True, "message": "User deleted"})

@app.route("/api/admin/activity-logs", methods=["GET"])
@admin_required
def get_activity_logs():
    limit = request.args.get("limit", 100, type=int)
    all_logs = []
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    for username, data in users.items():
        for log in data.get("activity_logs", [])[:limit]:
            all_logs.append({
                "username": username,
                "action": log.get("action"),
                "details": log.get("details"),
                "ip": log.get("ip"),
                "timestamp": log.get("timestamp")
            })
    
    all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return jsonify({"success": True, "logs": all_logs[:limit]})

@app.route("/api/admin/settings", methods=["GET", "POST"])
@admin_required
def manage_settings():
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)
    
    if request.method == "GET":
        return jsonify({"success": True, "settings": settings})
    
    data = request.get_json()
    settings.update(data)
    
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    
    log_activity(session['username'], "update_settings", "Updated system settings")
    
    return jsonify({"success": True, "message": "Settings updated"})

@app.route("/api/admin/backup", methods=["POST"])
@admin_required
def create_full_backup():
    backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    # Backup users.json
    shutil.copy2(USERS_FILE, f"{backup_path}_users.json")
    
    # Backup settings.json
    shutil.copy2(SETTINGS_FILE, f"{backup_path}_settings.json")
    
    # Backup subdomains.json
    shutil.copy2(SUBDOMAINS_FILE, f"{backup_path}_subdomains.json")
    
    # Backup USERS directory
    shutil.make_archive(backup_path + "_users_data", 'zip', USERS_DIR)
    
    log_activity(session['username'], "create_backup", f"Created backup: {backup_name}")
    
    return jsonify({"success": True, "backup_name": backup_name})

# ============== SERVER MANAGEMENT ==============
running_procs = {}

@app.route("/servers")
@login_required
def get_servers():
    user_servers_dir = get_user_servers_dir()
    os.makedirs(user_servers_dir, exist_ok=True)
    
    servers = []
    if os.path.exists(user_servers_dir):
        for folder in os.listdir(user_servers_dir):
            folder_path = os.path.join(user_servers_dir, folder)
            if os.path.isdir(folder_path):
                # Check if running
                proc_key = f"{session['username']}_{folder}"
                is_running = proc_key in running_procs and running_procs[proc_key].poll() is None
                
                # Get created time
                created_at = datetime.fromtimestamp(os.path.getctime(folder_path)).isoformat()
                
                servers.append({
                    "id": len(servers) + 1,
                    "name": folder,
                    "folder": folder,
                    "status": "running" if is_running else "stopped",
                    "created_at": created_at
                })
    
    # Update user's servers list
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if session['username'] in users:
        users[session['username']]["servers"] = servers
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    
    return jsonify({"success": True, "servers": servers})

@app.route("/add", methods=["POST"])
@login_required
def add_server():
    data = request.get_json()
    name = data.get("name", "").strip()
    template = data.get("template", "blank")
    
    folder = sanitize_name(name)
    user_servers_dir = get_user_servers_dir()
    target = os.path.join(user_servers_dir, folder)
    
    if os.path.exists(target):
        return jsonify({"success": False, "message": "Server already exists"}), 409
    
    os.makedirs(target)
    
    # Create template files
    if template == "python":
        with open(os.path.join(target, "main.py"), "w") as f:
            f.write('#!/usr/bin/env python3\nprint("Hello from ZAINU HOST!")\nprint("Your Python server is running!")\n\n# Add your code here\n')
    elif template == "node":
        with open(os.path.join(target, "index.js"), "w") as f:
            f.write('console.log("Node.js server running on ZAINU HOST!");\nconsole.log("Server started successfully!");\n')
    elif template == "html":
        with open(os.path.join(target, "index.html"), "w") as f:
            f.write('''<!DOCTYPE html>
<html>
<head>
    <title>My Website - ZAINU HOST</title>
    <style>
        body { font-family: Arial; text-align: center; padding: 50px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }
        h1 { font-size: 48px; }
    </style>
</head>
<body>
    <h1>🚀 Welcome to ZAINU HOST!</h1>
    <p>Your website is running successfully.</p>
    <p>Powered by ZAINU HOST</p>
</body>
</html>''')
    elif template == "react":
        with open(os.path.join(target, "index.html"), "w") as f:
            f.write('''<!DOCTYPE html>
<html>
<head>
    <title>React App</title>
    <script src="https://unpkg.com/react@18/umd/react.development.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        function App() { return <h1>🚀 React App on ZAINU HOST!</h1>; }
        ReactDOM.createRoot(document.getElementById("root")).render(<App />);
    </script>
</body>
</html>''')
    
    log_activity(session['username'], "create_server", f"Created server: {name} with template {template}")
    update_storage_used(session['username'])
    
    return jsonify({"success": True, "message": "Server created"})

@app.route("/server/start/<folder>", methods=["POST"])
@login_required
def start_server(folder):
    proc_key = f"{session['username']}_{folder}"
    
    if proc_key in running_procs and running_procs[proc_key].poll() is None:
        return jsonify({"success": False, "message": "Already running"})
    
    user_servers_dir = get_user_servers_dir()
    server_path = os.path.join(user_servers_dir, folder)
    
    if not os.path.exists(server_path):
        return jsonify({"success": False, "message": "Server not found"})
    
    # Find startup file
    startup_file = None
    for file in os.listdir(server_path):
        if file.endswith(('.py', '.js', '.html')):
            startup_file = file
            break
    
    if not startup_file:
        return jsonify({"success": False, "message": "No startup file found. Create main.py, index.js, or index.html"})
    
    log_path = os.path.join(server_path, "server.log")
    
    # Clear old logs
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] Server starting...\n")
    
    log_file = open(log_path, "a", encoding="utf-8")
    
    try:
        if startup_file.endswith('.py'):
            proc = subprocess.Popen(
                [sys.executable, "-u", startup_file],
                cwd=server_path,
                stdout=log_file,
                stderr=log_file
            )
        elif startup_file.endswith('.js'):
            proc = subprocess.Popen(
                ["node", startup_file],
                cwd=server_path,
                stdout=log_file,
                stderr=log_file
            )
        else:
            # For HTML, serve with simple HTTP server
            proc = subprocess.Popen(
                [sys.executable, "-m", "http.server", "8080"],
                cwd=server_path,
                stdout=log_file,
                stderr=log_file
            )
        
        running_procs[proc_key] = proc
        log_activity(session['username'], "start_server", f"Started server: {folder} with {startup_file}")
        
        return jsonify({"success": True, "message": f"Server started with {startup_file}"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/server/stop/<folder>", methods=["POST"])
@login_required
def stop_server(folder):
    proc_key = f"{session['username']}_{folder}"
    
    if proc_key in running_procs:
        try:
            proc = running_procs[proc_key]
            proc.terminate()
            proc.wait(timeout=5)
        except:
            try:
                proc.kill()
            except:
                pass
        finally:
            del running_procs[proc_key]
    
    log_activity(session['username'], "stop_server", f"Stopped server: {folder}")
    
    return jsonify({"success": True})

@app.route("/server/restart/<folder>", methods=["POST"])
@login_required
def restart_server(folder):
    await stop_server(folder)
    time.sleep(1)
    return start_server(folder)

@app.route("/server/stats/<folder>")
@login_required
def server_stats(folder):
    proc_key = f"{session['username']}_{folder}"
    running = proc_key in running_procs and running_procs[proc_key].poll() is None
    
    cpu = 0
    memory = 0
    uptime = 0
    
    if running:
        try:
            p = psutil.Process(running_procs[proc_key].pid)
            cpu = p.cpu_percent(interval=0.1)
            memory = p.memory_info().rss / 1024 / 1024
            uptime = time.time() - p.create_time()
        except:
            pass
    
    # Get logs
    user_servers_dir = get_user_servers_dir()
    log_path = os.path.join(user_servers_dir, folder, "server.log")
    logs = ""
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors='ignore') as f:
                logs = f.read()[-10000:]
        except:
            pass
    
    # Count files
    files_count = 0
    server_path = os.path.join(user_servers_dir, folder)
    if os.path.exists(server_path):
        files_count = len([f for f in os.listdir(server_path) if os.path.isfile(os.path.join(server_path, f))])
    
    return jsonify({
        "running": running,
        "cpu": round(cpu, 1),
        "memory": round(memory, 1),
        "uptime": round(uptime),
        "logs": logs,
        "files_count": files_count,
        "ip": socket.gethostbyname(socket.gethostname())
    })

# ============== FILE MANAGEMENT ==============
@app.route("/files/list/<folder>")
@login_required
def list_files(folder):
    user_servers_dir = get_user_servers_dir()
    path = os.path.join(user_servers_dir, folder)
    files = []
    
    if os.path.exists(path):
        for f in os.listdir(path):
            if f in ["server.log"]:
                continue
            f_path = os.path.join(path, f)
            files.append({
                "name": f,
                "size": os.path.getsize(f_path),
                "size_mb": round(os.path.getsize(f_path) / 1024, 1),
                "is_dir": os.path.isdir(f_path),
                "modified": datetime.fromtimestamp(os.path.getmtime(f_path)).isoformat()
            })
    
    files.sort(key=lambda x: (x["is_dir"], x["name"]))
    return jsonify({"success": True, "files": files})

@app.route("/files/content/<folder>/<path:filename>")
@login_required
def get_file_content(folder, filename):
    user_servers_dir = get_user_servers_dir()
    file_path = os.path.join(user_servers_dir, folder, filename)
    
    if not os.path.exists(file_path):
        return jsonify({"success": False, "content": ""})
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return jsonify({"success": True, "content": f.read()})
    except UnicodeDecodeError:
        return jsonify({"success": False, "content": "Binary file cannot be displayed"})
    except:
        return jsonify({"success": False, "content": ""})

@app.route("/files/save/<folder>/<path:filename>", methods=["POST"])
@login_required
def save_file_content(folder, filename):
    user_servers_dir = get_user_servers_dir()
    file_path = os.path.join(user_servers_dir, folder, filename)
    data = request.json
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(data.get('content', ''))
        log_activity(session['username'], "edit_file", f"Edited: {filename}")
        update_storage_used(session['username'])
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/files/upload/<folder>", methods=["POST"])
@login_required
def upload_file(folder):
    user_servers_dir = get_user_servers_dir()
    uploaded_files = request.files.getlist('files[]')
    results = []
    
    for f in uploaded_files:
        if f and f.filename:
            safe_name = sanitize_name(f.filename)
            save_path = os.path.join(user_servers_dir, folder, safe_name)
            f.save(save_path)
            results.append({"name": safe_name})
    
    log_activity(session['username'], "upload_files", f"Uploaded {len(results)} files to {folder}")
    update_storage_used(session['username'])
    
    return jsonify({"success": True, "uploaded": len(results)})

@app.route("/files/delete/<folder>", methods=["POST"])
@login_required
def delete_file(folder):
    data = request.get_json()
    filename = data.get("name")
    
    user_servers_dir = get_user_servers_dir()
    file_path = os.path.join(user_servers_dir, folder, filename)
    
    if os.path.isfile(file_path):
        os.remove(file_path)
    elif os.path.isdir(file_path):
        shutil.rmtree(file_path)
    
    log_activity(session['username'], "delete_file", f"Deleted: {filename}")
    update_storage_used(session['username'])
    
    return jsonify({"success": True})

@app.route("/files/rename/<folder>", methods=["POST"])
@login_required
def rename_file(folder):
    data = request.get_json()
    old_name = data.get("old")
    new_name = sanitize_name(data.get("new"))
    
    user_servers_dir = get_user_servers_dir()
    old_path = os.path.join(user_servers_dir, folder, old_name)
    new_path = os.path.join(user_servers_dir, folder, new_name)
    
    os.rename(old_path, new_path)
    log_activity(session['username'], "rename_file", f"Renamed: {old_name} -> {new_name}")
    
    return jsonify({"success": True})

@app.route("/files/create-folder/<folder>", methods=["POST"])
@login_required
def create_folder(folder):
    data = request.get_json()
    folder_name = sanitize_name(data.get("name"))
    
    user_servers_dir = get_user_servers_dir()
    folder_path = os.path.join(user_servers_dir, folder, folder_name)
    
    os.makedirs(folder_path, exist_ok=True)
    
    return jsonify({"success": True})

# ============== SUBDOMAIN ROUTES ==============
@app.route("/api/subdomain/create", methods=["POST"])
@login_required
def create_subdomain():
    data = request.get_json()
    subdomain = sanitize_name(data.get("subdomain"))
    server_folder = data.get("server_folder", "")
    
    with open(SUBDOMAINS_FILE, "r", encoding="utf-8") as f:
        subdomains = json.load(f)
    
    full_domain = f"{subdomain}.zainu.host"
    
    if full_domain in subdomains:
        return jsonify({"success": False, "message": "Subdomain already taken"})
    
    subdomains[full_domain] = {
        "owner": session['username'],
        "server_folder": server_folder,
        "created_at": datetime.now().isoformat()
    }
    
    with open(SUBDOMAINS_FILE, "w", encoding="utf-8") as f:
        json.dump(subdomains, f, indent=2)
    
    # Add to user's subdomains list
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if session['username'] in users:
        if "subdomains" not in users[session['username']]:
            users[session['username']]["subdomains"] = []
        users[session['username']]["subdomains"].append(full_domain)
        
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2)
    
    log_activity(session['username'], "create_subdomain", f"Created: {full_domain}")
    
    return jsonify({
        "success": True,
        "domain": full_domain,
        "message": f"Subdomain created: {full_domain}"
    })

@app.route("/api/subdomain/list")
@login_required
def list_subdomains():
    with open(SUBDOMAINS_FILE, "r", encoding="utf-8") as f:
        subdomains = json.load(f)
    
    user_subdomains = []
    for domain, data in subdomains.items():
        if data.get("owner") == session['username']:
            user_subdomains.append({
                "domain": domain,
                "server": data.get("server_folder"),
                "created_at": data.get("created_at")
            })
    
    return jsonify({"success": True, "subdomains": user_subdomains})

@app.route("/api/domain/set", methods=["POST"])
@login_required
def set_custom_domain():
    data = request.get_json()
    folder = data.get("folder")
    domain = data.get("domain", "").strip()
    
    # Store custom domain mapping (simplified)
    log_activity(session['username'], "set_domain", f"Set domain {domain} for {folder}")
    
    return jsonify({"success": True, "message": "Domain mapping saved"})

# ============== API KEYS ==============
@app.route("/api/apikeys/generate", methods=["POST"])
@login_required
def generate_api_key():
    data = request.get_json()
    name = data.get("name", "Default Key")
    
    api_key = f"zainu_{secrets.token_urlsafe(32)}"
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    if "api_keys" not in users[session['username']]:
        users[session['username']]["api_keys"] = []
    
    users[session['username']]["api_keys"].append({
        "key": api_key,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "last_used": None
    })
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    log_activity(session['username'], "generate_api_key", f"Created: {name}")
    
    return jsonify({"success": True, "api_key": api_key})

@app.route("/api/apikeys/list")
@login_required
def list_api_keys():
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    return jsonify({
        "success": True,
        "api_keys": users.get(session['username'], {}).get("api_keys", [])
    })

@app.route("/api/apikeys/revoke", methods=["POST"])
@login_required
def revoke_api_key():
    data = request.get_json()
    key_to_revoke = data.get("key")
    
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        users = json.load(f)
    
    keys = users[session['username']].get("api_keys", [])
    users[session['username']]["api_keys"] = [k for k in keys if k.get("key") != key_to_revoke]
    
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    
    log_activity(session['username'], "revoke_api_key", f"Revoked key")
    
    return jsonify({"success": True})

# ============== TEMPLATES ==============
@app.route("/api/templates")
@login_required
def get_templates():
    templates = [
        {"id": "blank", "name": "Blank Project", "icon": "📄", "description": "Start from scratch"},
        {"id": "python", "name": "Python App", "icon": "🐍", "description": "Python/Flask template"},
        {"id": "node", "name": "Node.js App", "icon": "💚", "description": "Node.js/Express template"},
        {"id": "html", "name": "Static Website", "icon": "🌐", "description": "HTML/CSS/JS site"},
        {"id": "react", "name": "React App", "icon": "⚛️", "description": "React.js template"}
    ]
    return jsonify({"success": True, "templates": templates})

# ============== ENVIRONMENT VARIABLES ==============
@app.route("/api/env/<folder>", methods=["GET", "POST"])
@login_required
def manage_env_vars(folder):
    user_servers_dir = get_user_servers_dir()
    env_file = os.path.join(user_servers_dir, folder, ".env.json")
    
    if request.method == "GET":
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                env_vars = json.load(f)
        else:
            env_vars = {}
        return jsonify({"success": True, "env_vars": env_vars})
    
    data = request.get_json()
    env_vars = data.get("env_vars", {})
    
    with open(env_file, "w", encoding="utf-8") as f:
        json.dump(env_vars, f, indent=2)
    
    log_activity(session['username'], "update_env", f"Updated env vars for {folder}")
    
    return jsonify({"success": True})

# ============== SYSTEM INFO ==============
@app.route("/api/system/cpu")
def system_cpu():
    return jsonify({"cpu": psutil.cpu_percent(interval=0.5)})

@app.route("/api/system/memory")
def system_memory():
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    return jsonify({
        "memory": f"{mem.used // (1024**2)} MB / {mem.total // (1024**2)} MB",
        "disk": f"{disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB",
        "uptime": time.time() - psutil.boot_time()
    })

# ============== ANNOUNCEMENT ==============
@app.route("/api/announcement")
def get_announcement():
    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        settings = json.load(f)
    return jsonify({
        "announcement": settings.get("announcement", ""),
        "maintenance_mode": settings.get("maintenance_mode", False)
    })

# ============== RUN SERVER ==============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)