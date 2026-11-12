"""Shared terminal instructions. Passwords are never requested here."""

EARTHDATA_STEPS = """
Earthdata login is not available in this terminal yet.

Do this on your Mac:
1. Open Safari or Chrome to https://urs.earthdata.nasa.gov/users/new
   Create a free Earthdata account if you do not already have one.
2. In Cursor, open the menu Terminal → New Terminal.
3. Paste these commands, one at a time:

   source "$HOME/anaconda3/etc/profile.d/conda.sh"
   conda activate vela
   cd ~/Desktop/MODISVIIRS
   earthaccess login

4. Type your Earthdata username and password in that terminal when it asks.
   The password stays on this Mac. Do not paste it into the chat.
5. If a browser page asks you to authorize data access, click Authorize.
6. Come back to the chat and send: Earthdata login is done
""".strip()

FIRMS_STEPS = """
The FIRMS map key is not in .env yet.

Do this on your Mac:
1. Open https://firms.modaps.eosdis.nasa.gov/api/map_key/
2. Request a free map key. NASA emails it to you.
3. In Cursor, open the file .env in this project.
4. Put the key on the FIRMS_MAP_KEY= line. No quotes and no spaces.
5. Save the file.
6. Stop Vela if it is running (click in the terminal and press Control-C), then start it again
   with the command in the README.
7. Tell the chat: the map key is in .env
   Do not paste the key.
""".strip()
