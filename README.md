# LAN Chat

A self-hosted, moderator-gated chat room for a **local network**. Run it on
one computer and let other devices on the same Wi-Fi or LAN join in their
browsers. LAN Chat uses Flask, SQLite, and Server-Sent Events; chat data stays
on the server computer.

## Features

- **Approval-gated joining** — visitors request access; a moderator approves
  or rejects them.
- **Real-time chat** — messages and presence are updated using Server-Sent
  Events.
- **Moderator controls** — manage join requests and members, clear the room,
  and block names.
- **Persistent history** — messages are stored in SQLite and survive restarts.
- **Voice messages** — record and send from the browser over HTTPS.
- **Offline-friendly** — dependencies can be bundled for use without internet.

## Requirements

- Python **3.9 or newer** on the computer that will host the chat.
- A browser on each participating device.
- Devices must be able to reach each other on the same Wi-Fi/LAN.
- For HTTPS (needed for browser microphone access), OpenSSL must be installed
  if you want LAN Chat to generate its own certificate.

No separate database server is needed; SQLite is included with Python.

## Install and run

Choose the commands for your operating system. Run them from the LAN Chat
project folder (the folder containing `main.py`).

### Windows

Install Python 3.9+ from [python.org](https://www.python.org/downloads/) or
the Microsoft Store. If using the python.org installer, enable **Add Python
to PATH**.

Open PowerShell in the project folder:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

If PowerShell prevents activation of the virtual environment, you can skip
activation and run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

If `py` is not available, use `python` instead. To use Command Prompt rather
than PowerShell, activate with `.venv\Scripts\activate.bat`.

### macOS

Install Python 3.9+ from [python.org](https://www.python.org/downloads/) or
with [Homebrew](https://brew.sh/). Open Terminal in the project folder:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

### Linux

Install Python 3.9+, `pip`, and the venv support package using your
distribution's package manager if they are not already installed. For example,
on Debian or Ubuntu:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Then, from the project folder:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```

When the server starts, it prints a URL. Open that URL on the host computer,
or use the LAN URL printed by the server on another device connected to the
same network. Keep the terminal open while using the chat; press **Ctrl+C** to
stop the server.

### Joining from other devices

The host binds to all network interfaces by default (`0.0.0.0`), allowing
other devices on the LAN to connect. Use the LAN address printed by the
server, for example `http://192.168.1.42:5000`. Do not use `localhost` on a
phone or another computer; that points back to that device, not to the host.

If other devices cannot connect:

1. Confirm they are on the same Wi-Fi/LAN as the host.
2. Allow Python (or inbound TCP traffic on port **5000**) through the host's
   firewall for **private/local networks only**. Firewall steps differ by OS.
3. Check that the router or Wi-Fi access point does not have client/AP
   isolation enabled.

## Moderator password

Set a unique moderator password before sharing the server. The built-in
default is `admin`, which is not suitable for a shared network.

**PowerShell:**

```powershell
$env:LAN_CHAT_ADMIN_PASSWORD = "choose-a-strong-password"
python main.py
```

**Command Prompt:**

```bat
set LAN_CHAT_ADMIN_PASSWORD=choose-a-strong-password
python main.py
```

**macOS / Linux:**

```bash
export LAN_CHAT_ADMIN_PASSWORD='choose-a-strong-password'
python main.py
```

The environment variable applies to that terminal session. Alternatively,
pass `--admin-password "your-password"` when starting the server. The password
is not written to disk; LAN Chat keeps only a salted hash in memory.

## HTTPS and voice messages

Microphone access in browsers requires a secure context. For LAN access, start
the server with HTTPS:

```bash
python main.py --ssl
```

This command works the same in PowerShell, Command Prompt, macOS, and Linux.
On the first run, LAN Chat uses the system `openssl` command to create a
self-signed certificate and stores it in `certs/`. Install OpenSSL if it is
not already available, or provide your own PEM certificate and key:

```bash
python main.py --ssl --cert path/to/cert.pem --key path/to/key.pem
```

The certificate is self-signed, so browsers will show a security warning.
Only proceed if you recognize the LAN Chat host and trust the local network.
For a certificate trusted without a browser warning, configure a local CA
(for example, [mkcert](https://github.com/FiloSottile/mkcert)) and provide its
certificate and key. Keep private key files private.

## Configuration

For example:

```bash
python main.py --port 5000 --room "Engineering"
```

| Option | Default | Description |
| --- | --- | --- |
| `--host` | `0.0.0.0` | Network interface to bind |
| `--port` | `5000` | Port to listen on |
| `--room` | `LAN Chat` | Room name shown in the UI |
| `--db` | `data/lan-chat.db` | SQLite database file |
| `--admin-password` | `LAN_CHAT_ADMIN_PASSWORD`, else `admin` | Moderator password |
| `--rate` | `1.0` | Minimum seconds between messages per session; `0` disables the limit |
| `--ssl` / `--https` | Off | Enable HTTPS; required for microphone access from LAN devices |
| `--cert` and `--key` | Generated in `certs/` with `--ssl` | PEM certificate and private key; specify both together |

Use `python main.py --help` to see all available options.

## Run without internet

If Flask is not installed and the host has internet access, bundle the runtime
dependencies once:

```bash
python bundle_deps.py
```

Distribute the project folder, including the generated `deps/` directory, to
the offline host, then run `python main.py` there. Bundled dependencies may
contain platform-specific files, so create a separate bundle on each target
operating system and Python version. If you already installed Flask with
`requirements.txt`, no bundle is needed.

## Development and tests

Activate the virtual environment created above, then install the project
requirements and run:

```bash
python -m pytest -q
```

## Security and deployment notes

- LAN Chat is intended for trusted local networks, not direct public internet
  exposure.
- The built-in Flask development server is intended for LAN-scale use. For
  public or production deployments, use a production WSGI server and a
  properly configured HTTPS reverse proxy.
- Session cookies are signed and HTTP-only; mutating requests require a
  per-session CSRF token. User content is validated and rendered as text.
- The moderator password is hashed in memory and is not persisted.

## Project layout

```text
main.py           Entry point and command-line options
app.py            Flask application factory
config.py         Application configuration
db.py             SQLite persistence
routes.py         HTTP routes and Server-Sent Events
templates/        HTML template
static/           CSS and client-side JavaScript
tests/            pytest suite
bundle_deps.py    Offline dependency bundler
requirements.txt  Pinned Python dependencies
```

## License

[MIT](License)
