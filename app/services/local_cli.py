from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

COMMON_DIRS = [
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path.home() / ".local" / "bin",
    Path.home() / ".npm-global" / "bin",
]

if platform.system() == "Windows":
    for env_name, suffixes in (
        ("APPDATA", ["npm"]),
        ("LOCALAPPDATA", ["Programs/nodejs", "Microsoft/WindowsApps"]),
        ("ProgramFiles", ["nodejs"]),
    ):
        base = os.environ.get(env_name)
        if base:
            COMMON_DIRS.extend(Path(base) / suffix for suffix in suffixes)


def _find_executable(name: str) -> str | None:
    if platform.system() == "Windows":
        for candidate in (f"{name}.exe", f"{name}.cmd", f"{name}.bat", name):
            found = shutil.which(candidate)
            if found:
                return found
    else:
        found = shutil.which(name)
        if found:
            return found
    for folder in COMMON_DIRS:
        for suffix in ((".exe", ".cmd", ".bat", "") if platform.system() == "Windows" else ("",)):
            candidate = folder / f"{name}{suffix}"
            if candidate.exists():
                return str(candidate)
    return None


def _safe_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BEARER_TOKEN"):
        env.pop(key, None)
    return env


def _run(args: list[str], *, timeout: int = 20, cwd: str | None = None, input_text: str | None = None, env: dict | None = None):
    run_args = list(args)
    if platform.system() == "Windows" and run_args and Path(run_args[0]).suffix.lower() in {".cmd", ".bat"}:
        run_args = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", subprocess.list2cmdline(run_args)]
    return subprocess.run(
        run_args,
        cwd=cwd,
        env=env or _safe_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input_text,
    )


def _version(path: str | None) -> str | None:
    if not path:
        return None
    try:
        result = _run([path, "--version"], timeout=6)
        value = (result.stdout or result.stderr or "").strip()
        return value.splitlines()[0][:160] if value else None
    except Exception:
        return None


def codex_status() -> dict:
    path = _find_executable("codex")
    data = {"provider":"codex_local","label":"Codex / ChatGPT Subscription","installed":bool(path),"authenticated":False,"subscription":False,"path":path,"version":_version(path),"message":""}
    if not path:
        data["message"] = "Codex CLI is not installed."
        return data
    try:
        result = _run([path, "login", "status"], timeout=8)
        text = "\n".join(filter(None, [result.stdout, result.stderr])).strip()
        low = text.lower()
        data["authenticated"] = result.returncode == 0 and ("logged in" in low or "authenticated" in low)
        data["subscription"] = data["authenticated"] and "chatgpt" in low
        data["message"] = "Signed in with ChatGPT." if data["subscription"] else (text[-300:] or "Sign in with ChatGPT.")
    except Exception as exc:
        data["message"] = str(exc)
    return data


def claude_status() -> dict:
    path = _find_executable("claude")
    data = {"provider":"claude_local","label":"Claude Code / Claude Subscription","installed":bool(path),"authenticated":False,"subscription":False,"path":path,"version":_version(path),"message":""}
    if not path:
        data["message"] = "Claude Code is not installed."
        return data
    for args in ([path, "auth", "status", "--text"], [path, "auth", "status"]):
        try:
            result = _run(args, timeout=8)
            text = "\n".join(filter(None, [result.stdout, result.stderr])).strip()
            low = text.lower()
            if result.returncode == 0:
                data["authenticated"] = any(x in low for x in ("logged in", "login method", "authenticated"))
                data["subscription"] = data["authenticated"] and any(x in low for x in ("pro", "max", "claude.ai", "subscription", "claude account"))
                data["message"] = "Signed in with a Claude subscription." if data["subscription"] else (text[-300:] or "Claude is signed in.")
                break
        except Exception:
            continue
    return data


def all_statuses() -> dict:
    return {"codex_local": codex_status(), "claude_local": claude_status()}


def _terminal(command: str) -> None:
    system = platform.system()
    if system == "Darwin":
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal"\nactivate\ndo script "{escaped}"\nend tell'])
        return
    if system == "Windows":
        subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/k", command], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return
    for terminal in ("x-terminal-emulator", "gnome-terminal", "konsole"):
        path = shutil.which(terminal)
        if path:
            subprocess.Popen([path, "-e", "bash", "-lc", command + "; exec bash"])
            return
    raise RuntimeError("Could not open a terminal window.")


def launch_login(provider: str) -> dict:
    if provider == "codex_local":
        path = _find_executable("codex")
        if not path:
            raise RuntimeError("Codex CLI is not installed.")
        _terminal(shlex.join([path, "login"]) if platform.system() != "Windows" else subprocess.list2cmdline([path, "login"]))
        return {"ok":True,"message":"Complete Sign in with ChatGPT in the terminal, then refresh."}
    if provider == "claude_local":
        path = _find_executable("claude")
        if not path:
            raise RuntimeError("Claude Code is not installed.")
        args = [path, "auth", "login", "--claudeai"]
        _terminal(shlex.join(args) if platform.system() != "Windows" else subprocess.list2cmdline(args))
        return {"ok":True,"message":"Complete Claude subscription sign-in, then refresh."}
    raise RuntimeError("Unsupported local provider.")


def _require(provider: str) -> str:
    status = codex_status() if provider == "codex_local" else claude_status()
    if not status["installed"]:
        raise RuntimeError(f"{status['label']} is not installed.")
    if not status["authenticated"]:
        raise RuntimeError(f"{status['label']} is not signed in.")
    return str(status["path"])


def _cli_error(result, label: str) -> str:
    """A short, readable error. The CLIs echo the whole prompt (often the
    full narration) before the real error line; never show that echo."""
    text = f"{result.stderr or ''}\n{result.stdout or ''}"
    errors = [line.strip() for line in text.splitlines() if re.match(r"\s*(ERROR|Error|error)\b[:\s]", line)]
    message = errors[-1] if errors else (text.strip().splitlines() or [f"{label} failed"])[-1]
    message = re.sub(r"^\s*(ERROR|Error|error)\s*:?\s*", "", message)[:400]
    if re.search(r"usage limit|rate limit|quota|too many requests", text, re.IGNORECASE):
        return f"{label} hit its usage limit: {message}"
    return f"{label} failed: {message}"


def generate_local_text(provider: str, model: str, system_prompt: str, user_prompt: str) -> str:
    if provider == "codex_local":
        path = _require(provider)
        with tempfile.TemporaryDirectory(prefix="ytnews-codex-") as tmp:
            output = Path(tmp) / "last.txt"
            args = [path, "exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never", "--cd", tmp, "--output-last-message", str(output)]
            selected = model if model and model != "default" else "gpt-5.6-terra"
            args += ["--model", selected, "-"]
            prompt = f"<SYSTEM>\n{system_prompt}\n</SYSTEM>\n\n<USER>\n{user_prompt}\n</USER>"
            result = _run(args, timeout=900, cwd=tmp, input_text=prompt)
            if result.returncode != 0:
                raise RuntimeError(_cli_error(result, "Codex"))
            if output.exists() and output.read_text(encoding="utf-8").strip():
                return output.read_text(encoding="utf-8").strip()
            return (result.stdout or "").strip()
    if provider == "claude_local":
        path = _require(provider)
        with tempfile.TemporaryDirectory(prefix="ytnews-claude-") as tmp:
            system_path = Path(tmp) / "system.txt"
            system_path.write_text(system_prompt, encoding="utf-8")
            # Text in, text out. Without this the CLI may spend extra turns
            # reading its empty temp folder or searching the web.
            args = [path, "-p", "--output-format", "text", "--permission-mode", "plan",
                    "--disallowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch",
                    "WebSearch", "Task", "NotebookEdit", "TodoWrite",
                    "--system-prompt-file", str(system_path)]
            if model and model != "default":
                args += ["--model", model]
            result = _run(args, timeout=900, cwd=tmp, input_text=user_prompt)
            if result.returncode != 0:
                raise RuntimeError(_cli_error(result, "Claude Code"))
            return (result.stdout or "").strip()
    raise RuntimeError("Unsupported subscription provider")
