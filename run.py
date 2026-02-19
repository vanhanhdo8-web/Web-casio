import subprocess
import os
import mimetypes
from flask import Flask, request, abort, jsonify, g, send_file, redirect, url_for
import argparse
import uuid
import time
import json
import threading
import webbrowser
import tempfile
import importlib.util
import sys

# Thêm đường dẫn để import libdecompiler
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'asmapp', 'decompiler'))
try:
    from libdecompiler import get_disas, get_commands, decompile
except ImportError:
    print("⚠️  Không thể import libdecompiler. Chức năng decompiler sẽ không hoạt động.")
    def get_disas(*args, **kwargs): raise NotImplementedError
    def get_commands(*args, **kwargs): raise NotImplementedError
    def decompile(*args, **kwargs): raise NotImplementedError

# Thư mục gốc của dự án (nơi chứa file run.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== THƯ MỤC =====
UPLOAD_FOLDER = os.path.join(tempfile.gettempdir(), 'casio_uploads')  # Dùng temp để có quyền ghi
HEX_FOLDER = os.path.join(BASE_DIR, 'hex')
ASM_FOLDER = os.path.join(BASE_DIR, 'asm')
PIXEL_FOLDER = os.path.join(BASE_DIR, 'pixel')
SPELL_FOLDER = os.path.join(BASE_DIR, 'spell')
DONATE_FOLDER = os.path.join(BASE_DIR, 'donate')
LIENHE_FOLDER = os.path.join(BASE_DIR, 'lienhe')

ASMAPP_BASE = os.path.join(BASE_DIR, 'asmapp')
COMPILER_BASE = os.path.join(ASMAPP_BASE, 'compiler')
DECOMPILER_MODELS_DIR = os.path.join(ASMAPP_BASE, 'decompiler', 'models')

MODELS = ['580vnx', '880btg']

# Tạo thư mục cần thiết
for folder in [UPLOAD_FOLDER, HEX_FOLDER, ASM_FOLDER, PIXEL_FOLDER, SPELL_FOLDER, DONATE_FOLDER, LIENHE_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

for model in MODELS:
    model_dir = os.path.join(COMPILER_BASE, model)
    if not os.path.exists(model_dir):
        os.makedirs(model_dir)
        print(f"📁 Đã tạo thư mục compiler: {model_dir}")

# Kiểm tra file compiler
for model in MODELS:
    compiler_file = os.path.join(COMPILER_BASE, model, 'compiler_.py')
    if not os.path.exists(compiler_file):
        print(f"⚠️  Cảnh báo: Thiếu file compiler cho {model}")

# Kiểm tra thư mục decompiler models
def check_decompiler_models():
    if not os.path.isdir(DECOMPILER_MODELS_DIR):
        print(f"⚠️  Không tìm thấy thư mục decompiler models")
        return
    models = [d for d in os.listdir(DECOMPILER_MODELS_DIR) if os.path.isdir(os.path.join(DECOMPILER_MODELS_DIR, d))]
    required_files = ['config.py', 'disas', 'gadgets', 'labels']
    for model in models:
        model_path = os.path.join(DECOMPILER_MODELS_DIR, model)
        missing = [f for f in required_files if not os.path.isfile(os.path.join(model_path, f))]
        if missing:
            print(f"⚠️  Model '{model}' thiếu: {', '.join(missing)}")
check_decompiler_models()

app = Flask(__name__, static_folder=None)

# ===== BLACKLIST =====
BLOCK_EXT = {".py", ".sh", ".php", ".asp", ".exe", ".dll", ".so"}
BLOCK_FILES = {"run.py", "app.py", "config.py", ".env"}
BLOCK_DIRS = {".git", "__pycache__", "venv", "env"}

# ===== LOGGING =====
@app.before_request
def log_input_stdout():
    g.req_id = str(uuid.uuid4())
    g.start_time = time.time()
    body = ""
    if request.method in ["POST", "PUT"]:
        try:
            body = request.get_data(cache=True, as_text=True)
        except:
            body = "<binary>"
    print(json.dumps({
        "type": "REQUEST",
        "req_id": g.req_id,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": request.method,
        "path": request.path,
        "remote": request.remote_addr,
        "body": body[:200] + ("..." if len(body) > 200 else "")
    }, ensure_ascii=False), flush=True)

# ===== API UPLOAD =====
@app.route("/upload", methods=["POST"])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "Không tìm thấy file"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Tên file trống"}), 400

    filename = file.filename
    if '..' in filename or filename.startswith('.'):
        return jsonify({"error": "Tên file không hợp lệ"}), 400

    ext = os.path.splitext(filename)[1].lower()
    if ext in BLOCK_EXT or filename in BLOCK_FILES:
        return jsonify({"error": f"Loại file {ext if ext else 'này'} bị chặn"}), 403

    safe_filename = f"{uuid.uuid4().hex}_{filename}"
    file_path = os.path.join(UPLOAD_FOLDER, safe_filename)
    file.save(file_path)
    return jsonify({
        "status": "success",
        "filename": filename,
        "saved_as": safe_filename,
        "size": os.path.getsize(file_path)
    })

# ===== COMPILER FUNCTION =====
def compiler():
    data = request.get_json(silent=True)
    if not data or "code" not in data:
        return jsonify({"returncode": -1, "stderr": "invalid input", "stdout": ""}), 400
    code = data["code"]
    model = data.get("model", "580vnx")
    try:
        compiler_path = os.path.join(COMPILER_BASE, model, "compiler_.py")
        if not os.path.exists(compiler_path):
            return jsonify({"returncode": -4, "stderr": f"Compiler {model} not found", "stdout": ""}), 404
        # Dùng sys.executable thay vì "python" để đảm bảo đúng interpreter
        p = subprocess.run(
            [sys.executable, compiler_path, "-f", "hex"],
            input=code, text=True, capture_output=True, timeout=15
        )
        return jsonify({"returncode": p.returncode, "stderr": p.stderr, "stdout": p.stdout})
    except subprocess.TimeoutExpired:
        return jsonify({"returncode": -2, "stderr": "compile timeout", "stdout": ""}), 408
    except Exception as e:
        return jsonify({"returncode": -5, "stderr": str(e), "stdout": ""}), 500

# ===== SPELL API =====
@app.route("/spell", methods=["POST"])
def spell():
    data = request.get_json(silent=True)
    if not data or "code" not in data:
        return jsonify({"out": "invalid input", "returncode": -1}), 400
    code = data["code"]
    try:
        spell_path = os.path.join(BASE_DIR, "util", "spell.py")
        if not os.path.exists(spell_path):
            return jsonify({"out": "spell tool not found", "returncode": -4}), 404
        p = subprocess.run(
            [sys.executable, spell_path],
            input=code, text=True, capture_output=True, timeout=10
        )
        return jsonify({"out": p.stdout if p.stdout else p.stderr, "returncode": p.returncode})
    except subprocess.TimeoutExpired:
        return jsonify({"out": "timeout", "returncode": -2}), 408
    except Exception as e:
        return jsonify({"out": str(e), "returncode": -3}), 500

# ===== DECOMPILER API =====
def load_model_config(model_name):
    config_path = os.path.join(DECOMPILER_MODELS_DIR, model_name, 'config.py')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f'Không tìm thấy config.py cho model {model_name}')
    spec = importlib.util.spec_from_file_location('config', config_path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    return config

@app.route("/decompile", methods=["POST"])
def decompile_api():
    data = request.get_json(silent=True)
    if not data or "code" not in data:
        return jsonify({"returncode": -1, "stderr": "invalid input", "stdout": ""}), 400

    code = data["code"]
    model = data.get("model", "580vnx")

    model_path = os.path.join(DECOMPILER_MODELS_DIR, model)
    if not os.path.isdir(model_path):
        return jsonify({"returncode": -1, "stderr": f"model {model} not found", "stdout": ""}), 400

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, dir=tempfile.gettempdir()) as f:
        f.write(code)
        input_path = f.name
    output_path = tempfile.mktemp(suffix='.asm', dir=tempfile.gettempdir())

    try:
        cfg = load_model_config(model)
        disas = get_disas(os.path.join(model_path, 'disas'))
        gadgets = get_commands(os.path.join(model_path, 'gadgets'))
        labels = get_commands(os.path.join(model_path, 'labels'))

        result_lines = decompile(
            input_path, output_path,
            disas, gadgets, labels,
            cfg.start_ram, cfg.end_ram
        )

        asm_output = ''.join(result_lines)
        return jsonify({
            "returncode": 0,
            "stderr": "",
            "stdout": asm_output
        })

    except Exception as e:
        return jsonify({
            "returncode": -3,
            "stderr": str(e),
            "stdout": ""
        }), 500
    finally:
        try:
            if os.path.exists(input_path):
                os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
        except Exception:
            pass

# ===== STATIC PAGES =====
def serve_static(path, folder=None):
    if folder:
        base = folder
    else:
        base = BASE_DIR

    full = os.path.join(base, path)
    full = os.path.normpath(full)

    if not full.startswith(base):
        abort(403)
    for d in BLOCK_DIRS:
        if os.path.commonpath([full, os.path.join(BASE_DIR, d)]) == os.path.join(BASE_DIR, d):
            abort(403)
    if os.path.basename(full) in BLOCK_FILES:
        abort(403)
    if any(full.endswith(ext) for ext in BLOCK_EXT):
        abort(403)

    if os.path.isdir(full):
        index = os.path.join(full, "index.html")
        if os.path.exists(index):
            full = index
        else:
            abort(403)
    if not os.path.exists(full):
        abort(404)

    mime, _ = mimetypes.guess_type(full)
    return send_file(full, mimetype=mime or "application/octet-stream")

# Các route trang con
@app.route("/hex", methods=["GET", "POST"])
@app.route("/hex/", methods=["GET", "POST"])
def hex_page():
    return serve_static("index.html", HEX_FOLDER)

@app.route("/asm", methods=["GET", "POST"])
def asm_page():
    if request.method == "POST" and request.is_json:
        data = request.get_json(silent=True)
        if data and "code" in data:
            return compiler()
    return serve_static("index.html", ASM_FOLDER)

@app.route("/pixel", methods=["GET", "POST"])
def pixel_page():
    return serve_static("index.html", PIXEL_FOLDER)

@app.route("/spell", methods=["GET", "POST"])
def spell_page():
    if request.method == "POST" and request.is_json:
        data = request.get_json(silent=True)
        if data and "code" in data:
            return spell()
    return serve_static("index.html", SPELL_FOLDER)

@app.route("/donate", methods=["GET", "POST"])
def donate_page():
    return serve_static("index.html", DONATE_FOLDER)

@app.route("/lienhe", methods=["GET", "POST"])
def lienhe_page():
    return serve_static("index.html", LIENHE_FOLDER)

@app.route("/gop", methods=["GET", "POST"])
def gop_redirect():
    return redirect(url_for('donate_page'), 301)

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def serve(path):
    if ".." in path or "~" in path:
        abort(403)
    if path == "":
        path = "index.html"
    return serve_static(path, BASE_DIR)

# ===== ERROR HANDLERS =====
@app.errorhandler(403)
def forbidden(e):
    return jsonify({"error": "Truy cập bị từ chối"}), 403

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Không tìm thấy tài nguyên"}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Lỗi máy chủ nội bộ"}), 500

@app.after_request
def log_output_stdout(response):
    duration = round((time.time() - g.get("start_time", time.time())) * 1000, 2)
    try:
        body = response.get_data(as_text=True)
        if len(body) > 200:
            body = body[:200] + "..."
    except:
        body = "<binary>"
    print(json.dumps({
        "type": "RESPONSE",
        "req_id": g.get("req_id"),
        "status": response.status_code,
        "duration_ms": duration,
        "body": body
    }, ensure_ascii=False), flush=True)
    return response

def open_browser(port):
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{port}')

if __name__ == "__main__":
    # Chạy local: python run.py [port] [--no-browser]
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, nargs="?", default=5000, help="cổng chạy server")
    parser.add_argument("--no-browser", action="store_true", help="không tự động mở trình duyệt")
    args = parser.parse_args()

    # Nếu biến môi trường PORT tồn tại (Render), dùng nó, không thì dùng port từ dòng lệnh
    port = int(os.environ.get("PORT", args.port))

    print(f"\n🚀 Casio Tool Server đang chạy tại http://0.0.0.0:{port}")
    print(f"📁 Thư mục gốc: {BASE_DIR}")
    print(f"📁 Uploads (tạm): {UPLOAD_FOLDER}\n")

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()
        print("⏳ Đang mở trình duyệt...")

    app.run("0.0.0.0", port, debug=True)
