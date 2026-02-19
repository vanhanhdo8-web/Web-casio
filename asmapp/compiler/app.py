import subprocess
import os
import mimetypes
from flask import Flask, request, abort, jsonify, g
import argparse
import uuid
import time
import json

parser = argparse.ArgumentParser()
parser.add_argument("port", type=int, help="port input")
args = parser.parse_args()

BASE_DIR = os.getcwd()

app = Flask(__name__, static_folder=None)

# ===== blacklist =====
BLOCK_EXT = {".py", ".sh"}
BLOCK_FILES = {"run.py"}
BLOCK_DIRS = {".git", "__pycache__"}

@app.before_request
def log_input_stdout():
    g.req_id = str(uuid.uuid4())
    g.start_time = time.time()

    body = request.get_data(cache=True, as_text=True)

    print(json.dumps({
        "type": "REQUEST",
        "req_id": g.req_id,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": request.method,
        "path": request.path,
        "remote": request.remote_addr,
        "headers": dict(request.headers),
        "query": request.args.to_dict(),
        "body": body
    }, ensure_ascii=False), flush=True)

# ===== serve file như http.server =====
@app.route("/", defaults={"path": ""}, methods=["GET"])
@app.route("/<path:path>", methods=["GET"])
def serve(path):
    if ".." in path:
        abort(403)

    if path == "":
        path = "index.html"

    full = os.path.join(BASE_DIR, path)

    # block dir
    for d in BLOCK_DIRS:
        if full.startswith(os.path.join(BASE_DIR, d)):
            abort(403)

    # block file
    if os.path.basename(full) in BLOCK_FILES:
        abort(403)

    if any(full.endswith(ext) for ext in BLOCK_EXT):
        abort(403)

    # directory → index.html hoặc autoindex
    if os.path.isdir(full):
        index = os.path.join(full, "index.html")
        if os.path.exists(index):
            full = index
        else:
            files = os.listdir(full)
            return "<br>".join(files)

    if not os.path.exists(full):
        abort(404)

    mime, _ = mimetypes.guess_type(full)
    with open(full, "rb") as f:
        return f.read(), 200, {"Content-Type": mime or "application/octet-stream"}

# ===== POST API =====
@app.route("/compiler", methods=["POST"])
def compiler():
    data = request.get_json(silent=True)

    if not data or "code" not in data:
        return jsonify({
            "returncode": -1,
            "stderr": "invalid input",
            "stdout": ""
        }), 400

    code = data["code"]
    # Lấy machine từ request, mặc định là 580vnx
    machine = data.get("machine", "580vnx")

    # Whitelist các máy được hỗ trợ
    allowed_machines = {"580vnx", "880btg"}
    if machine not in allowed_machines:
        return jsonify({
            "returncode": -1,
            "stderr": f"invalid machine: {machine}",
            "stdout": ""
        }), 400

    # Xây dựng đường dẫn tuyệt đối đến compiler (thư mục con ngay cạnh run.py)
    compiler_path = os.path.join(BASE_DIR, machine, "compiler_.py")
    if not os.path.isfile(compiler_path):
        return jsonify({
            "returncode": -1,
            "stderr": f"compiler not found for {machine}",
            "stdout": ""
        }), 500

    try:
        p = subprocess.run(
            ["python", compiler_path, "-f", "hex"],
            input=code,
            text=True,
            capture_output=True,
            timeout=15
        )

        return jsonify({
            "returncode": p.returncode,
            "stderr": p.stderr,
            "stdout": p.stdout
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            "returncode": -2,
            "stderr": "compile timeout",
            "stdout": ""
        }), 408

    except Exception as e:
        return jsonify({
            "returncode": -3,
            "stderr": str(e),
            "stdout": ""
        }), 500

@app.after_request
def log_output_stdout(response):
    duration = round((time.time() - g.get("start_time", time.time())) * 1000, 2)

    try:
        body = response.get_data(as_text=True)
    except Exception:
        body = "<binary>"

    print(json.dumps({
        "type": "RESPONSE",
        "req_id": g.get("req_id"),
        "status": response.status_code,
        "duration_ms": duration,
        "headers": dict(response.headers),
        "body": body
    }, ensure_ascii=False), flush=True)

    return response

if __name__ == "__main__":
    app.run("0.0.0.0", args.port, debug=True)