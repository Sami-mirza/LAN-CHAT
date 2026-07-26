# LAN Chat

A lightweight chat server that runs entirely on your local network. No internet required. Perfect for classrooms, offices, events, or anywhere the WiFi works but the internet does not.

Built with Python and Flask. One person runs the server, everyone else joins through a browser.

---

## What It Does

- Hosts a real-time chat room on your local WiFi or router
- New users must request to join and get approved by the admin
- Admin can kick users, clear chat history, and control who enters
- No accounts, no passwords, no cloud storage, no tracking
- Everything runs in memory — nothing is saved to disk

---

## Requirements

- Python 3.7 or higher
- A WiFi router or local network that all participants can connect to

---

## Quick Start

### Step 1: Get the Code

Clone the repository or download the ZIP:

```bash
git clone https://github.com/Sami-mirza/LAN-CHAT.git
cd LAN-CHAT
Step 2: Install Flask (One Time)
If you have internet access, install Flask normally:
bash
pip install flask
If you do not have internet, the script can auto-install Flask to a local deps/ folder on first run. Just run the script and it will handle it.
Step 3: Start the Server
bash
python lan_chat.py
You will see output like this:
plain
============================================================
      LAN CHAT SERVER
============================================================
  Room Name : LAN Chat
  Your IP   : 192.168.1.42
  Port      : 5000
------------------------------------------------------------
  http://192.168.1.42:5000
------------------------------------------------------------
  Press Ctrl+C to stop
============================================================
Keep this terminal window open. That is your server running.
Step 4: Share the Link
Tell everyone on the same WiFi to open the link shown in their browser:
plain
http://192.168.1.42:5000
Replace 192.168.1.42 with whatever IP address your terminal shows.
They do not need to install anything. Any device with a browser works — phone, laptop, tablet.
How It Works
For the Host (Admin)
When you run the script, you are the admin. You will see:
A Requests button that shows pending join requests
An Online button that shows who is currently connected
A Clear button to wipe the chat history
A Kick button next to each non-admin user
When someone new opens the link, they see a "Request to Join" screen. They type their name and send the request. You click Approve to let them in, or Reject to block them. Once approved, they automatically enter the chat.
For Participants
Open the link in any browser
Enter your name and click Send Request
Wait for the admin to approve you
Start chatting
Customization
Change the port if 5000 is already in use:
bash
python lan_chat.py --port 8080
Change the room name:
bash
python lan_chat.py --room "My Room"
Both at once:
bash
python lan_chat.py --port 8080 --room "My Room"
Important Notes
Only one person should run the server. If two people run it, you get two separate chat rooms.
Everything lives in memory. When you stop the server with Ctrl+C, all messages and user data are gone forever. This is by design.
Names must be unique. If "Alice" is taken, no one else can use it.
Kicked users are banned for the session. They cannot rejoin with the same name until the server restarts.
Troubleshooting
"No module named flask"
Run pip install flask or let the script auto-install it on first run.
"Address already in use"
Port 5000 is taken by another program. Use a different port:
bash
python lan_chat.py --port 8080
Friends cannot connect
Table
Check	Solution
Same WiFi?	Everyone must be on the same router or network
Firewall?	Temporarily disable your firewall or allow Python through
Wrong IP?	Share the IP shown in the terminal, not 127.0.0.1
Windows network profile?	Set it to Private instead of Public
"This site cannot be reached"
Make sure the server is still running in the terminal
Double-check the IP address for typos
Try opening http://127.0.0.1:5000 on the host computer to test
Phone will not load the page
Make sure the phone is on the same WiFi as the host laptop
Try disabling mobile data on the phone so it uses WiFi only
Some routers block device-to-device communication — check router settings
File Structure
plain
LAN-CHAT/
├── lan_chat.py          # Main server file — run this
├── README.md            # This file
└── deps/                # Auto-created if Flask is missing
    └── flask/           # Flask and dependencies