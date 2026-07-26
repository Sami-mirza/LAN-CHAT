 How to Use LAN Chat

A complete guide for anyone who finds this repo and wants to get chatting in under 2 minutes.

 Step 1: Get the Code

Option A: Clone with Git (if you have internet)
bash
git clone https://github.com/Sami-mirza/LAN-CHAT.git
cd LAN-CHAT

 Step 2: Bundle Dependencies (One Time)

You need internet for this step only. After this, everything works offline forever.
Make sure you have Python installed:
bash
python --version
If you see something like Python 3.10.x, you're good. If not, install Python from python.org.
Now run the bundler:
bash
python bundle_deps.py
You'll see a bunch of download progress. When it finishes, you'll have a deps/ folder with Flask and everything it needs.
That's it. No more internet required.
 Step 3: Start the Chat Server
bash
python lan_chat_clean.py
You'll see output like this:
plain
============================================================
      💬  LAN CHAT SERVER — CLEAN UI  💬
============================================================
  Room Name : LAN Chat
  Your IP   : 192.168.1.42
  Port      : 5000
------------------------------------------------------------
  ➜  http://192.168.1.42:5000
------------------------------------------------------------
  Press Ctrl+C to stop
============================================================
Your job as host: Keep this terminal window open. That's the server running.

 Step 4: Share the Link

Tell everyone on the same WiFi to open this in their browser:
plain
http://192.168.1.42:5000
Replace 192.168.1.42 with whatever IP address your terminal shows.
They don't need to install anything. Just a browser. Phone, laptop, tablet — anything works.

 Step 5: Approve People (Admin Only)

When someone new opens the link, they see a "Request to Join" screen. They type their name and send the request.
You (the admin) will see:

A  Requests button in your admin bar

Click it — a drawer drops down showing pending names
Click ✓ Approve to let them in, or ✗ Reject to block them
Once approved, they automatically enter the chat. No refresh needed.

💬 Step 6: Chat

Type in the box. Hit Enter or click Send. Messages appear for everyone instantly.
Admin-only actions:
Table
Button	What It Does
 Requests	Show/hide pending join requests
👥 Online	Show/hide who's currently connected
Clear	Wipe all chat history (can't undo)
Kick (next to a name)	Remove that user and ban their name

🛑 Step 7: Stop the Server

Press Ctrl + C in the terminal. The server shuts down. All chat history is gone. This is normal — everything lives in memory.

 Troubleshooting


"No module named flask"
You skipped Step 2. Run:
bash
python bundle_deps.py
"Address already in use"
Port 5000 is taken. Use a different one:
bash
python lan_chat_clean.py --port 8080
Then share http://YOUR_IP:8080 instead.
Friends can't connect
Same WiFi? Everyone must be on the same router/network.
Firewall? Temporarily disable your firewall or allow Python through.
Wrong IP? Make sure you're sharing the IP shown in the terminal, not 127.0.0.1.
Windows network profile? Set it to "Private" instead of "Public."
"This site can't be reached"
Check that the server is still running in the terminal
Make sure there's no typo in the IP address
Try opening http://127.0.0.1:5000 on the host computer to test
Phone won't load the page
Make sure the phone is on the same WiFi as the laptop
Try disabling mobile data on the phone (forces it to use WiFi)
Some routers block device-to-device communication — check router settings
🎛️ Customization
Change the room name
bash
python lan_chat_clean.py --room "My Squad"
Change the port
bash
python lan_chat_clean.py --port 3000
Both
bash
python lan_chat_clean.py --port 3000 --room "Emergency Comms"
📁 What Each File Does
Table
File	Purpose
lan_chat_clean.py	The main chat server. Run this.
bundle_deps.py	Downloads Flask into deps/. Run once.
deps/	Folder with all Python packages. Created by bundler.
README.md	Project overview.
USAGE.md	This file. Detailed instructions.

💡 Pro Tips

Pin the terminal window so you don't accidentally close it
Bookmark the link on your phone for quick re-entry
Use a memorable port like 7777 or 8080 if 5000 is busy
For events: Open the admin page on your laptop and the chat page on a second device to test

❓ Still Stuck?

Open an issue on GitHub and describe:
What you did
What you expected
What actually happened (error messages help!)
Happy chatting — no internet required. 🎉