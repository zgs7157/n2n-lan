N2N Room Manager - Client (No Python required)
===============================================

English quick start · 中文见「使用说明.txt」

【Getting started】
1. Double-click start.bat (or n2n_room_manager.exe) to open the Room Manager.
   (On a non-Chinese Windows the UI opens in English automatically;
    switch language under "Tools & Settings -> Language".)
2. At the top, enter the server address given by the host, e.g.: 39.162.81.68:7654
   then click Save.
3. Host: click "Create Room (I'm host)":
   - tick "Password": a 6-digit room password is generated (send it SEPARATELY;
     wrong password cannot join);
   - untick "Password": no-password room, the room code is the only credential.
4. Friend: paste the room code -> (enter the password for password rooms) ->
   click "Join Room" (virtual IP is assigned automatically).
5. Host opens a Minecraft world and clicks "Open to LAN". In Minecraft Multiplayer
   you should see the host's world; if not, use Direct Connect with the host's
   virtual IP:25565 (host's virtual IP is usually 10.xx.0.1).

【Notes】
- First launch installs the TAP virtual NIC driver; click Yes/Install on the prompt.
- Driver install needs Administrator rights; allow it if your antivirus asks.
- Your Minecraft version and mods MUST match the host's, or you cannot join.
- Password rooms: room code + password = full credentials; send the password separately.
- Config is stored in config.json next to the exe; back it up before reinstalling.
