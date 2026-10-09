# n2n Room-based Virtual LAN (Minecraft Co-op over the Internet)

> **中文版见 [README.md](README.md)** · English: this file

Turn two (or more) PCs on different networks — with different accounts — into the
**same "room"**, so the game thinks you are on one local area network.
Built for **Minecraft (Java) and any game with a LAN/co-op mode**.

```
Public server (supernode, UDP 7654)
        │  Only does "room registration + NAT hole punching";
        │  peers connect P2P once established
        │  (falls back to server relay when hole punching fails)
   ┌────┴────┐
 Host PC      Friend PC
(10.x.0.1)   (10.x.0.2)
  └────┬─────┘
   Same room = same community (virtual LAN: ping each other,
   see each other's Minecraft LAN worlds)
```

- Engine: **n2n v3.1.1** (GPL open source, lucktu static build for Windows x64)
- Client app: **Room Manager** under `client/` (Python + tkinter, stdlib only)
- Virtual NIC driver: **OpenVPN TAP-Windows Adapter V9** (official signed components)

---

## 1. Deploy the Server (a machine with a public IP)

### Linux (recommended)
```bash
# Upload server/deploy_supernode.sh to the server and run (default UDP 7654):
bash deploy_supernode.sh          # custom port: bash deploy_supernode.sh 9527
```
The script: installs build deps → compiles n2n 3.1.1 → registers a systemd service
(auto-start on boot) → opens the firewall port.

**Also open the UDP port** in your cloud vendor's security group / firewall console.

### Windows server
Put `server/supernode.exe` and `server/start_supernode.bat` in the same folder and
run the bat as Administrator (it opens the firewall automatically).
Optional: `start_supernode.bat 7654 MyFederationName` silences the default-federation
WARNING in the supernode log (supernode-side only; clients need no change).

### Docker (backup)
```bash
bash deploy_supernode_docker.sh   # community image qida/n2n
```

**Verify the server**: `systemctl status n2n-supernode`, `ss -ulnp | grep 7654`.

---

## 2. Client Usage (install on every participating PC)

> **No-Python build (recommended)**: `n2n-lan-client.zip` ships a prebuilt
> `n2n_room_manager.exe` (PyInstaller single file, includes the Python runtime and GUI),
> so **friends do NOT need to install Python**. Unzip and double-click `start.bat`
> (or `n2n_room_manager.exe`). If Python 3 is already installed, you can also run
> `n2n_room_manager.py` (source version).

1. **Unzip** `n2n-lan-client.zip` anywhere (keep `bin/`, `driver/`, `tools/` next to the exe).
2. Double-click `start.bat` (or `n2n_room_manager.exe`) to open the Room Manager.
3. At the top, enter the server address: `your-server-public-ip:7654`, click **Save**.
4. Click **Install/Check TAP Driver** (required once; click "Yes" on the UAC prompt).
5. Click **Allow edge in Firewall** (click "Yes" on the UAC prompt).
6. **Host**: click "Create Room (I'm host)" → a room code is generated automatically.
   - Tick **Password**: a 6-digit room password is generated too — **send it separately**
     to friends (it is mixed into the encryption key derivation; wrong password cannot join);
   - Untick **Password**: a **no-password room** — the room code is the only credential.
7. **Friend**: paste the room code → (enter the password for password rooms) → click
   "Join Room" (virtual IP is auto-suggested; you can edit it, it must match the room's subnet).
8. Both status bars show "Connected"; they should `ping 10.x.0.1` each other.

> **Language**: the UI is bilingual (中文 / English). On a non-Chinese Windows it opens
> in English automatically; you can switch it anytime in "Tools & Settings → Language".

### Room code format
```
community@subnet#key      example: mc-pixel-creeper-1234@10.88.0#Ab3CdEfGhJ
```
- `community` = n2n community name (room isolation; must match within a room)
- `subnet` = first three octets of the virtual subnet (e.g. 10.88.0; all IPs in a room
  must share the subnet)
- `key` = transport encryption passphrase (n2n PSK; prevents eavesdropping / cross-room)
- **Room password (optional)**: host ticks "Password" to get a 6-digit password; the final
  key = `sha256(key:password)` first 16 hex chars. **Wrong password → different key →
  cannot decrypt peer traffic → effectively cannot join**, even if the room code leaks.
  No-password rooms use the room-code key directly.

### Linux client (when a friend uses Linux)

**Way A (easiest, no n2n needed)**: the Linux Minecraft Java edition connects straight
to the host's public IP: Multiplayer → Add Server → `your-public-ip:25565`
(requires TCP 25565 forwarded on the host router).

**Way B (join the n2n room, same experience as the Windows client)**:
use `client/join_room_linux.sh`:
1. Install n2n **v3** edge (**must be v3**, protocol-compatible with the server;
   distro apt packages are mostly old 2.x and are NOT compatible).
   Recommended: lucktu prebuilt Linux x64 build:
   ```bash
   wget https://github.com/lucktu/n2n/raw/master/Linux/n2n_v3_linux_x64_v3.1.1_r1255_static_by_heiye.tar.gz
   tar -xzf n2n_v3_linux_x64_v3.1.1_r1255_static_by_heiye.tar.gz
   sudo cp edge /usr/local/bin/ && edge --version   # check version
   ```
   (For ARM machines pick `n2n_v3_linux_arm64(aarch64)_v3.1.1_r1255_static_by_heiye.tar.gz`.)
2. Download and run the script (password room / no-password room):
   ```bash
   wget https://raw.githubusercontent.com/zgs7157/n2n-lan/main/client/join_room_linux.sh
   sudo bash join_room_linux.sh 'ROOM_CODE' 482913 your-server-ip:7654
   sudo bash join_room_linux.sh 'ROOM_CODE' your-server-ip:7654   # no-password
   ```
   (If raw.githubusercontent is unreachable, prefix the URL with `https://ghproxy.net/`.)
3. Minecraft Multiplayer → Direct Connect → `10.x.0.1:25565`.

> The script creates a virtual NIC `n2n0` and needs root; clean up as printed on exit.

---

## 3. Minecraft Notes

| Topic | Notes |
|---|---|
| Version | **Java and Bedrock editions cannot play together**; everyone must use the same version |
| Way 1 (recommended) | Host: open a world → ESC → "Open to LAN"; friends: Multiplayer → Direct Connect → `10.x.0.1:port` |
| Way 2 | LAN worlds appear in each other's Multiplayer list (multicast; `-E` is enabled by default) |
| Broadcast helper | If LAN discovery is flaky, tick "Auto-start broadcast helper" (WinIPBroadcast) |
| Other games | Any game with LAN/co-op mode works the same (Age of Empires, Red Alert, L4D, emulators, etc.) |

---

## 4. Security & Notes

- **Encryption**: the key in the room code is the n2n PSK (AES). Don't share it with
  strangers; to keep other rooms out, just generate a new room code.
- **Ports**: UDP only. Clients need no inbound ports (P2P hole punching); the server must
  open UDP 7654.
- **Antivirus**: the TAP driver and edge are from open-source/official channels; some
  AVs may flag driver installs — normal. Driver files were extracted from the Bugxia
  EasyN2N package (its own exe is an E-language program that may false-positive;
  **this tool does NOT include that exe** — only the official signed driver components).
- **Limit**: one PC can join one room at a time; rooms have no hard cap (≤10 recommended).

---

## 5. Remote Play (friends NOT on the same LAN)

If the server is behind a home LAN (e.g. 192.168.1.4), remote friends **cannot reach
the private IP** — you need one of:

### Option 1: Router port forwarding (preferred; needs public IPv4)
1. Open the router admin page (gateway, usually `192.168.1.1`), log in
   (credentials on the router/ONU label).
2. Find "Port Forwarding / Virtual Server / Port Mapping", add a rule:
   - Protocol: **UDP**; External port: **7654**; Internal IP: **192.168.1.4**; Internal port: **7654**
3. After it takes effect, every client (including you) sets the supernode to
   **your public IPv4:7654** (check it at `https://myip.ipip.net`, e.g. `39.162.81.68:7654`).
4. Home public IPs may change on re-dial; for long-term use set up DDNS on the router.
- The Windows firewall rule is added automatically by `start_supernode.bat` (UDP 7654 in).

### Option 2: Public supernode (backup when no public IP / router locked down)
Use a community-maintained public n2n supernode (e.g. Bugxia/EasyN2N nodes bj/cd/sh/gz).
**Everyone fills in the same public node address**:
- Room isolation is still guaranteed by `room code = community@subnet#key`;
- Cost: traffic does not pass through your own server; relies on the node's uptime/latency.

---

## 6. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| edge log: `supernode ... not responding` | UDP port not reachable: check cloud security group + system firewall + `ss -ulnp` |
| Both "Connected" but no ping | Subnet/key mismatch; or MTU issue — try MTU 1200 in settings |
| High latency | Hole punching failed → relay via server (strict NAT); move server closer; `-S` disables P2P |
| MC can't see each other's world | Version mismatch; or skip multicast and use Direct Connect with the virtual IP |
| Driver install fails | Run `client/driver/tap-windows/9.24.7.exe` manually |
| IP conflict after switching rooms | Set a free virtual IP in the subnet (e.g. .3 / .4) |

---

## Directory Structure

```
n2n-lan/
├── README.md / README_EN.md
├── LICENSE                   # MIT for this repo's own code
├── .gitignore
├── server/                      # public server side
│   ├── deploy_supernode.sh      #   Linux one-click (compile + systemd + firewall)
│   ├── deploy_supernode_docker.sh
│   ├── start_supernode.bat      #   Windows server launcher
│   ├── supernode.exe
│   └── supernode.service        #   systemd template
└── client/                      # Windows client (copy the whole folder for distribution)
    ├── start.bat                #   double-click to launch
    ├── n2n_room_manager.py      #   Room Manager (bilingual UI)
    ├── join_room_linux.sh       #   Linux one-click room join
    ├── bin/edge.exe             #   n2n v3.1.1 edge (lucktu build)
    ├── driver/tap-windows/      #   TAP driver (tapinstall + official installer)
    └── tools/WinIPBroadcast.exe #   LAN discovery broadcast helper (optional, not in repo)
```

## Open Source & Building

- **Source license**: this repo's own code (Room Manager, deploy scripts) is **MIT** (see LICENSE).
- **Bundled binaries**: `bin/edge.exe`, `bin/supernode.exe` are from n2n (**GPLv3**,
  github.com/ntop/n2n, lucktu prebuilt); `driver/tap-windows/` are OpenVPN TAP driver
  components (**GPLv2**). Redistribution must respect the respective licenses.
- **WinIPBroadcast.exe is NOT shipped in this repo**: it was extracted from the Bugxia
  EasyN2N package (bugxia.com) with unclear licensing; grab it yourself and place it in
  `client/tools/` if you want the broadcast helper (the app enables it only when the file exists).
- **Build the no-Python exe** (optional):
  ```bash
  python -m PyInstaller --noconsole --onefile --name n2n_room_manager client/n2n_room_manager.py
  ```
  Put the generated exe next to `bin/`, `driver/`, `tools/` and zip the whole folder.
- **Security note**: `client/config.json` contains your room keys/passwords — it is
  .gitignored, never commit it.

## Credits

- n2n engine / Windows binaries: github.com/ntop/n2n, github.com/lucktu/n2n
- TAP driver & broadcast tool: Bugxia EasyN2N (bugxia.com); driver = official signed OpenVPN components
- ghproxy.net mirror used where GitHub was unreachable
