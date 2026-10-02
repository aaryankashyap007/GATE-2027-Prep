#!/usr/bin/env python3
"""
GATE Prep Terminal App
-----------------------
A tiny terminal "app" that reads gate_cse_resources.json and lets you:
  - Browse subjects and resource categories
  - For YouTube playlists/channels: list videos (via yt-dlp) and play any
    one instantly in a separate mpv window (streamed, nothing downloaded)
  - Track which videos you've marked "watched" per playlist (persisted
    to a small local progress file, so it survives across runs)
  - mpv also auto-resumes the last playback position of a video by itself
  - For non-YouTube links (GitHub, GateOverflow, edX, LinkedIn) that
    genuinely need a browser (PDFs, exam portals, course pages), the app
    just prints the link and offers to open it in your default browser
  - For textbook entries: interactive checklist to mark chapters/sections
    read or unread, persisted just like video progress

Requirements (install once):
    sudo apt install mpv                        # Debian/Ubuntu
    sudo dnf install mpv                         # Fedora
    pip install -U yt-dlp                        # or your distro's yt-dlp package

Navigation: plain arrow keys (or j/k) + Enter, moving directly through the
normal terminal text — no popup window, no separate screen, nothing to
install for it. Esc/q goes back.

Usage:
    python3 gate_prep.py [path/to/gate_cse_resources.json]

If no path is given, it looks for gate_cse_resources.json in the same
directory as this script.
"""

import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import tty
import webbrowser
from pathlib import Path

# ----------------------------------------------------------------------
# Paths / config
# ----------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_JSON = SCRIPT_DIR / "gate_cse_resources.json"

STATE_DIR = Path.home() / ".gate_prep"
CACHE_DIR = STATE_DIR / "cache"          # cached playlist listings
PROGRESS_FILE = STATE_DIR / "progress.json"  # watched-video tracking

YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)

# ----------------------------------------------------------------------
# Colors / icons (ANSI — no extra dependency needed)
# ----------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    MAGENTA = "\033[35m"
    RED = "\033[31m"
    BLUE = "\033[34m"
    GREY = "\033[90m"


def c(text, *styles):
    return "".join(styles) + str(text) + C.RESET


CHECK_DONE = c("✔", C.GREEN)
CHECK_TODO = c("▢", C.GREY)

# Category keys (in the JSON) that hold link(s) that are typically YouTube
VIDEO_CATEGORY_KEYS = [
    "youtube_videos",
    "revision_and_pyq_video_solution",
    "nptel_lectures",
]

# Human-readable labels + icons for categories
CATEGORY_LABELS = {
    "youtube_videos": "YouTube Videos",
    "revision_and_pyq_video_solution": "Revision & PYQ Video Solutions",
    "nptel_lectures": "NPTEL Lectures",
    "other_video_resources": "Other Video Resources",
    "standard_textbook": "Standard Textbook",
    "topicwise_pyqs": "Topicwise PYQs",
    "free_tests": "Free Tests",
}

CATEGORY_ICONS = {
    "youtube_videos": "🎥",
    "revision_and_pyq_video_solution": "🔁",
    "nptel_lectures": "🎓",
    "other_video_resources": "🎬",
    "standard_textbook": "📘",
    "topicwise_pyqs": "📄",
    "free_tests": "🧪",
}


# ----------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------

def ensure_dirs():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def check_deps():
    missing = []
    for tool in ("yt-dlp", "mpv"):
        if shutil.which(tool) is None:
            missing.append(tool)
    if missing:
        print("Missing required tool(s):", ", ".join(missing))
        print("Install with, e.g.:")
        print("  Debian/Ubuntu: sudo apt install mpv && pip install -U yt-dlp")
        print("  Fedora:        sudo dnf install mpv yt-dlp   (or: pip install -U --user yt-dlp)")
        print("  Arch:          sudo pacman -S mpv yt-dlp")
        sys.exit(1)


def load_json(path: Path):
    if not path.exists():
        print(f"Could not find JSON file at: {path}")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(progress):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


def is_youtube(url: str) -> bool:
    return bool(YOUTUBE_RE.search(url))


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def pause():
    input(c("\nPress Enter to continue...", C.DIM))


def banner(title, subtitle=None):
    inner = max(len(title), len(subtitle) if subtitle else 0) + 4
    top = "╔" + "═" * inner + "╗"
    bot = "╚" + "═" * inner + "╝"
    print(c(top, C.CYAN))
    print(c("║  ", C.CYAN) + c(title.center(inner - 4), C.BOLD, C.CYAN) + c("  ║", C.CYAN))
    if subtitle:
        print(c("║  ", C.CYAN) + c(subtitle.center(inner - 4), C.DIM) + c("  ║", C.CYAN))
    print(c(bot, C.CYAN))


def section_header(text):
    print()
    print(c(f" {text} ", C.BOLD, C.MAGENTA))
    print(c("─" * (len(text) + 2), C.GREY))


# ----------------------------------------------------------------------
# Generic menu (fzf if available, else numbered input)
# ----------------------------------------------------------------------

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def choose(options, prompt="Select", use_fzf=False, allow_back=True):
    """
    options: list of display strings
    returns: index of chosen option, or None if user backs out
    Plain arrow-keys (or j/k) + Enter, drawn inline in the normal terminal
    flow — no popup window, no alternate screen.
    """
    labels = list(options)
    back_label = c("« Back", C.YELLOW)
    if allow_back:
        labels = labels + [back_label]

    if sys.stdin.isatty() and sys.stdout.isatty():
        idx = _inline_choose(labels, prompt)
    else:
        idx = _numbered_choose(labels, prompt)

    if idx is None:
        return None
    if allow_back and idx == len(labels) - 1:
        return None
    return idx


def _read_key():
    """Blocks for exactly one logical keypress on stdin (raw mode) and
    returns one of: 'UP','DOWN','ENTER','QUIT', or None for anything else."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch == "\x1b":
            # Might be a lone Esc, or the start of an arrow-key sequence
            # (Esc [ A/B/C/D). Peek briefly for the rest of the sequence.
            if select.select([sys.stdin], [], [], 0.05)[0]:
                ch2 = os.read(fd, 1).decode(errors="ignore")
                if ch2 == "[" and select.select([sys.stdin], [], [], 0.05)[0]:
                    ch3 = os.read(fd, 1).decode(errors="ignore")
                    return {"A": "UP", "B": "DOWN"}.get(ch3)
            return "QUIT"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("q", "Q"):
            return "QUIT"
        if ch in ("k", "K"):
            return "UP"
        if ch in ("j", "J"):
            return "DOWN"
        if ch == "\x03":  # Ctrl-C
            raise KeyboardInterrupt
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _inline_choose(labels, prompt):
    """Arrow-key / j-k + Enter picker drawn directly in the normal
    scrolling terminal (no alt-screen, no border)."""
    idx, top = 0, 0
    cols, rows = shutil.get_terminal_size(fallback=(100, 30))
    visible = max(rows - 4, 5)
    n = len(labels)

    def visible_slice():
        nonlocal top
        if idx < top:
            top = idx
        if idx >= top + visible:
            top = idx - visible + 1
        return range(top, min(n, top + visible))

    def render(first=False):
        rng = visible_slice()
        lines = []
        for i in rng:
            pointer = c("❯ ", C.CYAN) if i == idx else "  "
            lines.append(f"{pointer}{strip_ansi_safe(labels[i], cols - 2)}")
        return lines

    def strip_ansi_safe(text, width):
        # Truncate on the *visible* length, keeping ANSI codes intact.
        plain = strip_ansi(text)
        if len(plain) <= width:
            return text
        # fall back to plain truncation if it contains color codes we can't
        # easily re-slice without breaking escape sequences
        return plain[: max(width - 1, 0)] + "…"

    print(c(prompt, C.BOLD, C.MAGENTA))
    lines = render(first=True)
    for l in lines:
        print(l)
    footer = c("  ↑/↓ or j/k move · Enter select · Esc/q back", C.DIM)
    print(footer)
    printed = len(lines) + 1  # + footer line

    sys.stdout.write("\033[?25l")  # hide cursor
    sys.stdout.flush()
    try:
        while True:
            key = _read_key()
            if key == "UP":
                idx = (idx - 1) % n
            elif key == "DOWN":
                idx = (idx + 1) % n
            elif key == "ENTER":
                return idx
            elif key == "QUIT":
                return None
            else:
                continue

            lines = render()
            sys.stdout.write(f"\033[{printed}A")  # move cursor up
            for l in lines:
                sys.stdout.write("\033[2K" + l + "\n")
            sys.stdout.write("\033[2K" + footer + "\n")
            sys.stdout.flush()
            printed = len(lines) + 1
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()


def _numbered_choose(labels, prompt):
    """Last-resort fallback for non-interactive terminals (e.g. piped output)."""
    while True:
        section_header(prompt)
        for i, label in enumerate(labels, 1):
            print(f"  {c(str(i) + '.', C.CYAN)} {label}")
        raw = input(c("\n› ", C.BOLD, C.CYAN)).strip()
        if raw == "":
            continue
        if raw.lower() in ("q", "quit", "exit"):
            sys.exit(0)
        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(labels):
                return n - 1
        print(c("Invalid choice, try again.", C.RED))


def confirm(prompt, use_fzf=False):
    """Yes/No picker — arrow-key select instead of typing y/n."""
    idx = choose(["Yes", "No"], prompt=prompt, allow_back=False)
    return idx == 0


# ----------------------------------------------------------------------
# YouTube: list + play
# ----------------------------------------------------------------------

def fetch_playlist_entries(url: str, force_refresh=False):
    """Returns a list of dicts: {id, title, url, duration} using yt-dlp,
    caching results locally so repeat visits are instant."""
    cache_key = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:150]
    cache_file = CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists() and not force_refresh:
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    print("Fetching video list (yt-dlp)... this may take a few seconds.")
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "-J", url],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("Timed out fetching playlist.")
        return []

    if result.returncode != 0:
        print("Failed to fetch playlist listing:")
        print(result.stderr.strip()[-800:])
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Could not parse yt-dlp output.")
        return []

    entries = []
    for e in data.get("entries", []) or []:
        if not e:
            continue
        vid = e.get("id")
        title = e.get("title") or vid
        duration = e.get("duration")
        video_url = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
        if not video_url:
            continue
        entries.append({
            "id": vid,
            "title": title,
            "url": video_url,
            "duration": duration,
        })

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

    return entries


def fmt_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def play_video(url: str):
    print(c(f"\n▶  Playing: {url}", C.CYAN))
    print(c("   (opens in its own mpv window — close it to return here)", C.DIM))
    subprocess.run(["mpv", "--save-position-on-quit", url])


def browse_playlist(url: str, label: str, progress: dict, use_fzf: bool):
    watched = progress.setdefault(url, {})

    while True:
        entries = fetch_playlist_entries(url)
        if not entries:
            pause()
            return

        done = sum(1 for e in entries if watched.get(e["id"]))
        display = []
        for e in entries:
            tick = CHECK_DONE if watched.get(e["id"]) else CHECK_TODO
            dur = fmt_duration(e.get("duration"))
            dur_str = c(f" ({dur})", C.DIM) if dur else ""
            display.append(f"{tick} {e['title']}{dur_str}")

        display.append(c("↻ Refresh list", C.YELLOW))
        idx = choose(display, prompt=f"{label}  {c(f'[{done}/{len(entries)} watched]', C.GREEN)}",
                     use_fzf=use_fzf)
        if idx is None:
            return
        if idx == len(display) - 1:
            fetch_playlist_entries(url, force_refresh=True)
            continue

        entry = entries[idx]
        play_video(entry["url"])

        if confirm("Mark this video as watched?", use_fzf):
            watched[entry["id"]] = True
            save_progress(progress)


def open_in_browser(url: str, use_fzf: bool):
    print(c(f"\n🌐 This link needs a browser: {url}", C.YELLOW))
    if confirm("Open it now in your default browser?", use_fzf):
        try:
            webbrowser.open(url)
        except Exception:
            print(c("Could not auto-open — copy the link above manually.", C.RED))


# ----------------------------------------------------------------------
# Category / subject handling
# ----------------------------------------------------------------------

def handle_url_category(label, urls, progress, use_fzf):
    """A category that's a plain list of URL strings (video or non-video)."""
    if len(urls) == 1:
        handle_single_url(label, urls[0], progress, use_fzf)
        return

    display = [c(f"{label} #{i+1}", C.BOLD) + c(f"  — {u}", C.DIM) for i, u in enumerate(urls)]
    idx = choose(display, prompt=label, use_fzf=use_fzf)
    if idx is None:
        return
    handle_single_url(label, urls[idx], progress, use_fzf)


def handle_single_url(label, url, progress, use_fzf):
    if is_youtube(url):
        browse_playlist(url, label, progress, use_fzf)
    else:
        open_in_browser(url, use_fzf)


def handle_other_video_resources(items, progress, use_fzf):
    """List of {label, url} — could be a YT channel or an external course."""
    display = [c(it["label"], C.BOLD) + c(f"  — {it['url']}", C.DIM) for it in items]
    idx = choose(display, prompt="Other Video Resources", use_fzf=use_fzf)
    if idx is None:
        return
    it = items[idx]
    handle_single_url(it["label"], it["url"], progress, use_fzf)


def handle_textbook(items, progress, use_fzf):
    """Interactive checklist for textbook chapters/sections, with persisted
    read/unread status per chapter id."""
    while True:
        display = []
        flat = []  # (book_index, chapter_dict) for lookup by display index
        for bi, book in enumerate(items):
            total = len(book.get("chapters", []))
            read_map = progress.setdefault("textbooks", {})
            done = sum(1 for ch in book.get("chapters", []) if read_map.get(ch["id"]))
            count_str = c(f" [{done}/{total}]", C.GREEN) if total else ""
            display.append(c(f"— {book['title']} —{count_str}", C.BOLD, C.MAGENTA))
            flat.append(None)  # header row, not selectable meaningfully
            for ch in book.get("chapters", []):
                tick = CHECK_DONE if read_map.get(ch["id"]) else CHECK_TODO
                display.append(f"   {tick} {ch['label']}")
                flat.append((bi, ch))
            if not book.get("chapters"):
                display.append(c("   (no chapter breakdown given)", C.DIM))
                flat.append(None)

        idx = choose(display, prompt="Textbook chapters — toggle read/unread",
                     use_fzf=use_fzf)
        if idx is None:
            return

        target = flat[idx]
        if target is None:
            continue  # header or empty row, not toggleable

        _, ch = target
        read_map = progress.setdefault("textbooks", {})
        if read_map.get(ch["id"]):
            del read_map[ch["id"]]
        else:
            read_map[ch["id"]] = True
        save_progress(progress)


def category_progress_suffix(subject, key, progress):
    """Cheap, no-network progress hint shown next to a category label."""
    if key == "standard_textbook":
        books = subject.get("standard_textbook", [])
        total = sum(len(b.get("chapters", [])) for b in books)
        if not total:
            return ""
        read_map = progress.get("textbooks", {})
        done = sum(
            1 for b in books for ch in b.get("chapters", []) if read_map.get(ch["id"])
        )
        return c(f" [{done}/{total}]", C.GREEN)

    urls = []
    val = subject.get(key)
    if key == "other_video_resources":
        urls = [it["url"] for it in val if is_youtube(it["url"])]
    elif isinstance(val, list):
        urls = [u for u in val if isinstance(u, str) and is_youtube(u)]

    total = 0
    done = 0
    any_cached = False
    for u in urls:
        cache_key = re.sub(r"[^a-zA-Z0-9]+", "_", u)[:150]
        cache_file = CACHE_DIR / f"{cache_key}.json"
        if not cache_file.exists():
            continue
        any_cached = True
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            continue
        watched = progress.get(u, {})
        total += len(entries)
        done += sum(1 for e in entries if watched.get(e["id"]))

    if not any_cached:
        return ""
    return c(f" [{done}/{total}]", C.GREEN)


def subject_menu(subject, progress, use_fzf):
    while True:
        clear()
        banner(subject["name"], subject["abbreviation"])
        keys_present = [k for k in CATEGORY_LABELS if subject.get(k)]
        labels = [
            f"{CATEGORY_ICONS[k]}  {CATEGORY_LABELS[k]}" + category_progress_suffix(subject, k, progress)
            for k in keys_present
        ]
        idx = choose(labels, prompt="Choose a category", use_fzf=use_fzf)
        if idx is None:
            return

        key = keys_present[idx]
        value = subject[key]

        if key == "standard_textbook":
            handle_textbook(value, progress, use_fzf)
        elif key == "other_video_resources":
            handle_other_video_resources(value, progress, use_fzf)
        else:
            handle_url_category(CATEGORY_LABELS[key], value, progress, use_fzf)


def main():
    ensure_dirs()
    use_fzf = check_deps()
    progress = load_progress()

    json_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_JSON
    data = load_json(json_path)
    subjects = data["subjects"]

    while True:
        clear()
        banner(data["title"], "Terminal Prep Hub")
        labels = [f"📚  {s['name']}  " + c(f"({s['abbreviation']})", C.DIM) for s in subjects]
        idx = choose(labels, prompt="Choose a subject", use_fzf=use_fzf)
        if idx is None:
            print(c("\nBye — happy prepping. 👋", C.CYAN))
            return
        subject_menu(subjects[idx], progress, use_fzf)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
