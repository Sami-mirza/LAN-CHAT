═══════════════════════════════════════════════════════════════
        💬  LAN CHAT SERVER — OFFLINE SHARING GUIDE  💬
═══════════════════════════════════════════════════════════════

WHAT THIS IS:
  A chat server that works WITHOUT internet. Everyone on the
  same WiFi/router can chat through a browser.

  New users must request to join. The admin (you) approves or
  rejects each request.

═══════════════════════════════════════════════════════════════
FOR THE SENDER (You — needs internet ONCE):
═══════════════════════════════════════════════════════════════

  1. Make sure Python is installed on your computer.

  2. Run the bundler to download Flask into this folder:

       python bundle_deps.py

     This downloads Flask + all dependencies into the 'deps/'
     folder. You only need internet for this ONE step.

  3. Your folder now looks like this:

       chat_folder/
       ├── lan_chat_offline.py   ← main chat server
       ├── bundle_deps.py        ← bundler (you already ran it)
       ├── README.txt            ← this file
       └── deps/                 ← Flask + all packages
           ├── flask/
           ├── werkzeug/
           ├── jinja2/
           └── ...

  4. ZIP or copy this ENTIRE folder to a USB drive, or transfer
     it via wire cable / Bluetooth / local network to your friend.

═══════════════════════════════════════════════════════════════
FOR THE RECEIVER (Your friend — ZERO internet needed):
═══════════════════════════════════════════════════════════════

  1. Copy the entire folder to their computer.

  2. Make sure Python is installed.
     (If not, they need to install Python from python.org first.
      This is the ONLY thing they might need internet for.)

  3. Open terminal / command prompt in the folder.

  4. Run:

       python lan_chat_offline.py

  5. The server starts. They see their local IP address.
     Example: http://192.168.1.15:5000

  6. Others on the SAME WiFi/router open that link in any
     browser and send a join request.

  7. The admin (who ran the script) approves them from the
     "Pending Requests" panel.

═══════════════════════════════════════════════════════════════
IMPORTANT RULES:
═══════════════════════════════════════════════════════════════

  • ONLY ONE person runs the script per chat room.
    If two people run it, you get TWO separate chat rooms.

  • Everyone else just opens the link in their browser.
    They do NOT need to run any script.

  • The person running the script is the ADMIN.
    They control who joins and can kick users.

  • No internet is needed AFTER the initial bundling step.
    Everything works purely on the local WiFi network.

═══════════════════════════════════════════════════════════════
CUSTOMIZATION:
═══════════════════════════════════════════════════════════════

  Change port:
    python lan_chat_offline.py --port 8080

  Change room name:
    python lan_chat_offline.py --room "My Room"

═══════════════════════════════════════════════════════════════
TROUBLESHOOTING:
═══════════════════════════════════════════════════════════════

  "No module named flask"?
    → You forgot to run 'python bundle_deps.py' before sharing.

  "Address already in use"?
    → Port 5000 is taken. Use --port 8080

  Friends can't connect?
    → Make sure firewall allows the port.
    → Make sure everyone is on the SAME WiFi/router.
    → Try disabling firewall temporarily for testing.

═══════════════════════════════════════════════════════════════