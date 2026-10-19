"""Runs one connector inside the sandbox subprocess. Standard library only; no project imports.

    python -I -B _sandbox_runner.py <connector.py> <allowed port> <schema|sync>

Reads {"config": ..., "state": ...} as one JSON line on stdin and writes JSON lines to stdout:
{"type": "schema"|"record"|"state"|"blocked"|"error", ...}.

An audit hook blocks network connections other than 127.0.0.1:<port>, DNS lookups other than
localhost, file writes outside the working directory, and starting processes. This is a safety
measure for a local demo, not a security boundary: native code can bypass audit hooks.
"""

import importlib.util
import json
import os
import sys

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
BLOCKED_EVENTS = {
    "subprocess.Popen", "os.system", "os.exec", "os.spawn", "os.posix_spawn", "os.startfile",
    "os.fork", "os.kill", "ctypes.dlopen", "winreg.SetValue", "winreg.CreateKey", "winreg.DeleteKey",
}
PATH_EVENTS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "shutil.rmtree", "os.chmod", "os.truncate"}

_out = sys.stdout


def emit(obj):
    _out.write(json.dumps(obj, default=str) + "\n")
    _out.flush()


def install_guard(port: int, workdir: str) -> None:
    root = os.path.normcase(os.path.abspath(workdir))

    def inside(path) -> bool:
        if isinstance(path, int) or path is None:
            return True
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        p = os.path.normcase(os.path.abspath(path))
        return p == root or p.startswith(root + os.sep)

    def block(event, detail):
        emit({"type": "blocked", "event": event, "detail": str(detail)[:200]})
        raise PermissionError(f"blocked by sandbox: {event} {detail}")

    def hook(event, args):
        if event == "socket.connect":
            addr = args[1]
            if not (isinstance(addr, tuple) and addr[0] in LOCAL_HOSTS and addr[1] == port):
                block(event, addr)
        elif event == "socket.getaddrinfo":
            if args[0] not in LOCAL_HOSTS and args[0] not in {b"127.0.0.1", b"localhost"}:
                block(event, args[0])
        elif event == "open":
            path, mode, flags = args
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                mode is None and isinstance(flags, int) and flags & WRITE_FLAGS
            )
            if writing and not inside(path):
                block(event, path)
        elif event in PATH_EVENTS:
            for p in args[:2] if event == "os.rename" else args[:1]:
                if not inside(p):
                    block(event, p)
        elif event in BLOCKED_EVENTS:
            block(event, args[0] if args else "")

    sys.addaudithook(hook)


def main() -> int:
    path, port, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    payload = json.loads(sys.stdin.readline() or "{}")
    install_guard(port, os.getcwd())
    try:
        spec = importlib.util.spec_from_file_location("connector", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if mode == "schema":
            emit({"type": "schema", "schema": module.schema()})
            return 0
        gen = module.sync(payload.get("config"), payload.get("state"))
        while True:
            try:
                resource, record = next(gen)
            except StopIteration as stop:
                emit({"type": "state", "state": stop.value})
                return 0
            emit({"type": "record", "resource": resource, "record": record})
    except BaseException as e:  # report everything, including SystemExit from the connector
        emit({"type": "error", "error": f"{type(e).__name__}: {e}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
