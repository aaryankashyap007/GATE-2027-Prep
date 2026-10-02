# 🎓 GATE Prep Terminal App

A minimalist, distraction-free command-line application built to streamline your preparation for the GATE Computer Science (CSE) exam. 

This app reads a curated JSON database of study materials and lets you browse subjects, stream YouTube lectures directly from the terminal, and track your progress—all without getting sucked into browser algorithms and distractions.

## ✨ Features

* **Distraction-Free Video Streaming:** Browse YouTube playlists and channels from the terminal. Videos instantly play in a standalone `mpv` window using `yt-dlp` (no downloading required).
* **Keyboard Navigation:** Fast, intuitive inline UI using arrow keys (or Vim bindings: `j`/`k`) and `Enter`. No heavy GUI libraries required.
* **Progress Tracking:** Automatically tracks and saves your progress locally. It remembers which videos you've watched and which textbook chapters you've marked as read.
* **Auto-Resume:** Closes your video halfway? `mpv` auto-saves your position and resumes exactly where you left off.
* **Smart Link Handling:** For PDFs, exam portals, or resources that genuinely require a browser (like edX or GateOverflow tests), the app seamlessly hands them off to your system's default web browser.

## 🛠️ Requirements

The core script is written in pure Python (no external `pip` packages required for the UI), but it relies on two system tools for video handling:

1. **`mpv`** - A free, open-source, and cross-platform media player.
2. **`yt-dlp`** - A command-line audio/video downloader and extractor.

### Installation (Linux)

**Debian/Ubuntu:**
```bash
sudo apt update
sudo apt install mpv
pip install -U yt-dlp
```

**Fedora:**
```bash
sudo dnf install mpv yt-dlp
```

**Arch Linux:**
```bash
sudo pacman -S mpv yt-dlp
```

## 🚀 Usage

1. Ensure the `gate_cse_resources.json` file is in the same directory as the script.
2. Run the application:

```bash
python3 gate_prep.py
```

*Optional: You can pass a custom path to a different JSON file if needed:*
```bash
python3 gate_prep.py /path/to/custom_resources.json
```

### Controls
* **Up / Down** or **k / j**: Navigate menus
* **Enter**: Select an option, play a video, or toggle a checkbox
* **Esc** or **q**: Go back or quit the application

## 📂 How It Works

* **Data Source:** All subjects, YouTube links, NPTEL lectures, and textbooks are loaded from `gate_cse_resources.json`. You can easily add or modify resources by editing this file.
* **State Management:** Your cache (for fast playlist loading) and progress (watched videos, read chapters) are stored locally in your home directory under `~/.gate_prep/`. This ensures your study data persists across sessions.
