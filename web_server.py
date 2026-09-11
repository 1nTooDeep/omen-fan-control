#!/usr/bin/env python3
"""Local web UI for omen-fan-control. Standard library only, binds to 127.0.0.1."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from omen_logic import FanController

HOST = "127.0.0.1"
PORT = 8765
WEB_DIR = Path(__file__).resolve().parent / "web"

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

controller: FanController
_apply_lock = threading.Lock()


class FanError(Exception):
    """Invalid request or unmet precondition (HTTP 400)."""


def build_status() -> dict:
    rpm1 = rpm2 = 0
    try:
        rpm1, _ = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan1_input_path))
        rpm2, _ = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan2_input_path))
    except (OSError, ValueError):
        pass
    try:
        enable = controller.read_sys_file(controller.pwm1_enable_path)
    except (OSError, ValueError):
        enable = None
    try:
        cores = controller.get_all_core_temps() or []
    except Exception:
        cores = []
    return {
        "board": controller.config.get("cached_board_name", ""),
        "driver_installed": bool(controller.pwm1_path and controller.pwm1_path.exists()),
        "enable": enable,
        "cpu_temp": controller.get_cpu_temp(),
        "gpu_temp": controller.get_gpu_temp(),
        "fan1_rpm": rpm1,
        "fan2_rpm": rpm2,
        "mode": controller.config.get("mode", "auto"),
        "manual_pwm": int(controller.config.get("manual_pwm", 0)),
        "max_rpm": controller.get_effective_fan_max(),
        "cores": [[label, temp] for label, temp in cores],
    }


def _verify_write(path, expected: str) -> None:
    actual = controller.read_sys_file(path)
    if actual != expected:
        raise PermissionError(f"write to {path} did not take effect (read back: {actual})")


def apply_fan_mode(mode: str, value) -> dict:
    with _apply_lock:
        if mode == "manual":
            if not (controller.pwm1_path and controller.pwm1_path.exists()):
                raise FanError(
                    "手动模式需要补丁驱动（未找到 pwm1）。"
                    "先运行: sudo .venv/bin/python omen_cli.py install-patch temporary"
                )
            try:
                percent = int(value)
            except (TypeError, ValueError):
                raise FanError("手动模式需要 0-100 的数值")
            percent = max(0, min(100, percent))
            pwm = round(percent / 100 * 255)
            controller.set_fan_pwm(pwm)
            _verify_write(controller.pwm1_path, str(pwm))
            _verify_write(controller.pwm1_enable_path, "1")
            controller.config["mode"] = "manual"
            controller.config["manual_pwm"] = pwm
            controller.save_config()
            return {"ok": True, "mode": "manual", "percent": percent, "pwm": pwm}
        controller.set_fan_mode(mode)
        _verify_write(controller.pwm1_enable_path, "0" if mode == "max" else "2")
        controller.config["mode"] = mode
        controller.save_config()
        return {"ok": True, "mode": mode}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # silence per-request noise
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/status":
            try:
                self._send_json(200, build_status())
            except Exception as exc:
                self._send_json(500, {"error": f"status read failed: {exc}"})
            return
        entry = STATIC_FILES.get(path)
        if entry is None:
            self._send_json(404, {"error": "not found"})
            return
        fname, ctype = entry
        try:
            body = (WEB_DIR / fname).read_bytes()
        except OSError:
            self._send_json(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/api/fan":
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "请求体不是合法 JSON"})
            return
        mode = data.get("mode")
        if mode not in ("auto", "max", "manual"):
            self._send_json(400, {"error": "mode 必须是 auto / max / manual"})
            return
        try:
            result = apply_fan_mode(mode, data.get("value"))
        except FanError as exc:
            self._send_json(400, {"error": str(exc)})
        except PermissionError:
            self._send_json(500, {"error": "权限不足：请用 sudo 运行本服务"})
        except (OSError, RuntimeError) as exc:
            self._send_json(500, {"error": f"sysfs 写入失败: {exc}"})
        else:
            self._send_json(200, result)


def main() -> None:
    global controller
    controller = FanController()
    driver_ok = controller.pwm1_path and controller.pwm1_path.exists()
    print("OMEN Fan Control - Web UI")
    print(f"  Board: {controller.config.get('cached_board_name', '?')}")
    print(f"  Driver patch (pwm1): {'installed' if driver_ok else 'NOT installed (manual slider disabled)'}")
    print(f"  http://{HOST}:{PORT}  (localhost only)")
    if os.geteuid() != 0:
        print("  WARNING: 未以 root 运行，页面能看但改不了风扇")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
