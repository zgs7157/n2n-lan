# n2n 房间式虚拟局域网（MC 异地联机）

> **语言 / Language：中文** · [English](README_EN.md)

让不同网络、不同账号的两台（或多台）电脑，通过自己的公网服务器进入同一个「房间」，
在服务器看来你们处于同一个局域网——用于 **我的世界（MC）等支持局域网模式的游戏异地联机**。

```
公网服务器 (supernode, UDP 7654)
        │  只负责"房间登记 + NAT 打洞"，连接成功后双方 P2P 直连
        │  （打洞失败时自动降级为服务器中转）
   ┌────┴────┐
 房主PC      好友PC
 (10.x.0.1)  (10.x.0.2)
  └────┬─────┘
     同一房间 = 同一 community（虚拟局域网，互相 ping 通、互见 MC 局域网世界）
```

- 底层引擎：**n2n v3.1.1**（GPL 开源，lucktu 编译的 Windows x64 静态版）
- 客户端应用：`client/` 下的 **房间管理小工具**（Python + tkinter，纯标准库）
- 虚拟网卡驱动：**OpenVPN TAP-Windows Adapter V9**（官方签名组件，来自 Bug侠 EasyN2N 包内驱动，已单独抽出）

---

## 一、部署服务器（有公网 IP 的机器）

### Linux（推荐）
```bash
# 上传 server/deploy_supernode.sh 到服务器，执行（默认 UDP 7654）：
bash deploy_supernode.sh          # 可加端口参数：bash deploy_supernode.sh 9527
```
脚本自动：安装编译依赖 → 编译安装 n2n 3.1.1 → 注册 systemd 服务开机自启 → 防火墙放行。

**务必同时**在云厂商安全组/防火墙控制台放行该 UDP 端口。

### Windows 服务器
把 `server/supernode.exe` 和 `server/start_supernode.bat` 放同一目录，管理员运行 bat 即可（自动放行防火墙）。
可选：`start_supernode.bat 7654 自定义联邦名` 可消除 supernode 日志里的默认联邦名 WARNING（仅 supernode 端设置，客户端无需改动）。

### Docker（备用）
```bash
bash deploy_supernode_docker.sh   # 使用社区镜像 qida/n2n
```

**验证服务端**：`systemctl status n2n-supernode`、`ss -ulnp | grep 7654`。

---

## 二、客户端使用（每台参与电脑都装）

> **免 Python 版（推荐）**：`n2n-lan-client.zip` 已内置打包好的 `n2n_room_manager.exe`
> （PyInstaller 单文件版，含 Python 运行时与界面），**朋友电脑不用装 Python**，
> 解压后双击 `start.bat` 或直接双击 `n2n_room_manager.exe` 即可。
> 若机器上已装 Python 3，也可运行 `n2n_room_manager.py`（源码版）。

1. **解压** `n2n-lan-client.zip` 到任意位置（不要只拷 exe，需连同 `bin/`、`driver/`、`tools/` 一起）。
2. 双击 `start.bat`（或 `n2n_room_manager.exe`）打开房间管理小工具。
3. 顶部填服务器地址：`你的服务器公网IP:7654`，点 **保存**。
4. 点 **安装/检测虚拟网卡驱动**（首次必须，弹 UAC 点“是”）。
5. 点 **防火墙放行 edge**（弹 UAC 点“是”）。
6. **房主**：点「创建房间（我是房主）」→ 自动生成房间码。
   - 勾选「带密码」：另自动生成 **6 位房间密码**，**单独**发给好友（密码参与加密密钥派生，密码不对进不来）；
   - 不勾选「带密码」：**免密房间**，房间码即全部凭证。
7. **好友**：粘贴房间码 →（带密码房间需填房主单独发的密码）→ 点「加入房间」（虚拟 IP 自动建议，可手动改，必须与房间码网段一致）。
8. 双方状态栏显示“已连接”，相互 `ping 10.x.0.1` 应通。

### 房间码格式
```
community@网段#密钥      示例：mc-pixel-creeper-1234@10.88.0#Ab3CdEfGhJ
```
- `community` = n2n 社区名（房间隔离依据，同房间必须一致）
- `网段` = 虚拟子网前三段（如 10.88.0，同一房间内所有 IP 必须同网段）
- `密钥` = 传输加密口令（n2n PSK，防窃听防串房）
- **房间密码**（可选）：房主创建房间时勾选「带密码」生成 6 位数字密码；密码与密钥共同派生最终加密密钥
  （`sha256(密钥:密码)` 前 16 位），因此**密码错误 = 密钥不同 = 无法解密对端流量 = 进不来**，
  即使房间码泄露也无效。免密房间则直接用房间码自带密钥。

### Linux 客户端（朋友用 Linux 时）

**方式 A（最简单，无需 n2n）**：Linux 上的 MC Java 版直接连房主公网：
多人游戏 → 添加服务器 → `你的公网IP:25565`（需房主路由器已转发 TCP 25565）。

**方式 B（加入 n2n 房间，体验与 Windows 客户端一致）**：使用 `client/join_room_linux.sh`：
1. 安装 n2n **v3** 的 edge（**必须 v3**，与服务器协议一致；发行版 apt 源多为 2.x 老版本，不兼容）。
   推荐直接下载 lucktu 预编译 Linux 版（x64）：
   ```bash
   # 国内加速（gitee 镜像，推荐）：https://gitee.com/lucktu/n2nb
   # GitHub 直连或 ghproxy 镜像：
   wget https://github.com/lucktu/n2n/raw/master/Linux/n2n_v3_linux_x64_v3.1.1_r1255_static_by_heiye.tar.gz
   tar -xzf n2n_v3_linux_x64_v3.1.1_r1255_static_by_heiye.tar.gz
   sudo cp edge /usr/local/bin/ && edge --version   # 确认版本
   ```
   （ARM 机器选 `n2n_v3_linux_arm64(aarch64)_v3.1.1_r1255_static_by_heiye.tar.gz`）
2. 下载脚本并执行（带密码房 / 免密房）：
   ```bash
   wget https://raw.githubusercontent.com/zgs7157/n2n-lan/main/client/join_room_linux.sh
   sudo bash join_room_linux.sh '房间码' 482913 你的服务器IP:7654
   sudo bash join_room_linux.sh '房间码' 你的服务器IP:7654
   ```
   （raw.githubusercontent 直连不通时，给 wget 加 ghproxy 前缀：
   `https://ghproxy.net/https://raw.githubusercontent.com/...`）
3. MC 多人游戏 → 直接连接 → 填 `10.x.0.1:25565`。

> 注意：n2n 客户端必须为 **v3**（与服务器协议一致）。脚本会创建虚拟网卡 `n2n0`，需要 root；退出房间按脚本结尾提示清理。

### macOS 客户端（朋友用 Mac 时）

**方式 A（最简单，零安装，推荐）**：Mac 上的 MC Java 版直接连房主公网：
多人游戏 → 直接连接/添加服务器 → `你的公网IP:25565`（需房主路由器已转发 TCP 25565）。
Mac 完全不用装 n2n、不用装驱动、不用装任何软件——和手机好友进房是同一套原理。

**方式 B（加入 n2n 房间，体验与 Windows 客户端一致）**：使用 `client/install_mac.sh` + `client/start_mac.sh`：
1. **编译 n2n edge**（一键脚本自动完成，Intel 与 Apple 芯片通用）：
   ```bash
   cd client
   bash install_mac.sh      # 自动：检查 Homebrew → 装编译依赖 → 编译 n2n 3.1.1 → 拷 edge 到 bin/
   ```
   装好后 `bin/edge` 已就绪。若不想编译，也可 `sudo port install n2n`（MacPorts）。
2. **安装虚拟网卡驱动**（n2n 需要 TUN/TAP 接口）：
   - **Intel Mac**：`brew install --cask tuntap`，然后到「系统设置 → 隐私与安全性」允许内核扩展，重启生效；
   - **Apple 芯片（M 系列）**：官方 tuntap 内核扩展安装受限（需降低安全策略），这是 n2n 在 M 芯片上的已知难点；
     装不上的话直接走**方式 A**（好友直连）即可，完全不影响联机。
3. **启动客户端**：
   ```bash
   bash start_mac.sh        # 自检环境后打开图形界面，操作与 Windows 版一致
   ```
4. MC 多人游戏 → 直接连接 → 填 `10.x.0.1:25565`。

> 说明：Mac 客户端是**源码版**（Python + tkinter），需要本机 Python 3（`brew install python-tk`）。
> 打包成 .app 的步骤见 `client/make_mac_pkg.sh` 末尾注释。

### 房间聊天（电脑端，Windows 客户端内置）

创建/加入房间后点「房间聊天」即可使用，**不需要额外服务器**：

- 显示名：聊天窗口顶部填写，保存在本机（config.json），下次自动带出；
- 发送：底部输入消息按回车（或点「发送」），同房间、开着聊天窗口的成员都能收到；
- 原理：消息通过虚拟局域网 **UDP 广播**（`10.x.0.255:23333`）传递，payload 带 community 校验，跨房间消息会被忽略；
- 稳定性：双方 P2P 直连时最稳；走服务器中转时广播偶尔会丢，不影响游戏内联机。

---

## 三、MC 联机要点

| 事项 | 说明 |
|---|---|
| 版本 | **Java 版与基岩版互不互通**，所有成员版本必须一致 |
| 方式一（推荐） | 房主单人存档 → ESC → 对局域网开放；好友 多人游戏 → 直接连接 → 填 `10.x.0.1:端口` |
| 方式二 | 双方都能在多人游戏里看到对方的局域网世界（依赖组播，本工具已默认开 `-E` 接受组播） |
| 广播助手 | 若局域网发现不稳定，可勾选“自动启动广播助手”（WinIPBroadcast，双击 `tools/WinIPBroadcast.exe` 亦可） |
| 其他游戏 | 支持局域网联机的游戏（红警/星际/帝国时代/群星/求生之路/模拟器对战等）同理 |

---

## 四、安全与注意事项

- **加密**：房间码中的密钥即 n2n PSK（AES 加密），不要泄露给无关人员；想防“串房”，换房间码即可。
- **端口**：全程 UDP。客户端无需开放入站端口（P2P 打洞），服务器必须放行 UDP 7654。
- **杀软**：TAP 驱动与 edge 均来自开源/官方渠道；部分杀软对驱动安装有提示，属正常现象。
  驱动文件源自 Bug侠 EasyN2N 包（其 exe 为易语言程序可能误报，**本工具未包含其 exe**，仅抽出官方签名驱动组件）。
- **限制**：同一台电脑同时只能进一个房间；房间容量实际无上限（建议 ≤10 人流畅）。

---

## 六、异地联机（朋友不在同一局域网）

服务器在家庭宽带内网（如 192.168.1.4）时，异地的朋友**连不到内网 IP**，需要打通公网：

### 方式一：路由器端口转发（首选，需有公网 IPv4）
1. 浏览器打开路由器管理页（本机网关，通常是 `192.168.1.1`），登录（账号密码见路由器/光猫背面标签）。
2. 找到「端口转发 / 虚拟服务器 / 端口映射」，新增规则：
   - 协议：**UDP**；外部端口：**7654**；内网 IP：**192.168.1.4**；内部端口：**7654**
3. 保存生效后，所有客户端（含你）把 supernode 填成 **你的公网 IPv4:7654**（用 `https://myip.ipip.net` 查询当前值，如 `1.2.3.4:7654`）。
4. 注意：家庭宽带公网 IP 可能随重拨变化，长期使用建议在路由器里配置 DDNS 域名，或用域名代替 IP。
- 本机 Windows 防火墙放行由 `start_supernode.bat` 自动完成（UDP 7654 入站）。

### 方式二：公共 supernode（无公网 IP / 路由器改不了时的备用）
改用社区维护的公共 n2n supernode（如 Bug侠/EasyN2N 的 bj/cd/sh/gz 节点），**所有人填同一个公共节点地址**即可：
- 房间隔离仍由「房间码 = community@网段#密钥」保证，密钥即传输加密口令；
- 代价：不经过自己的服务器，依赖公共节点可用性与延迟。
- 公共节点地址获取：访问 bugxia.com 的 N2N 页面或 EasyN2N 使用文档。

### 方式三：手机好友进房（免安装，推荐给手机党）
手机端（iOS/安卓）无法免 root 跑 n2n，朋友手机建议直接连你开的 MC 服务器：
1. 桌面工具点「复制进房链接」，把链接发给好友（链接自动带上公网 IP 与房间名参数，如 `https://zgs7157.github.io/n2n-lan/join.html?ip=你的公网IP&port=25565&room=...`）；
2. 好友手机点开链接，看到房间地址后点「复制服务器地址」；
3. 打开 FCL → 多人游戏 → 添加服务器/直接连接 → 粘贴地址 → 加入服务器。
- 前提：路由器还要转发 **TCP 25565 → 192.168.1.4**（与 n2n 的 UDP 7654 是两个端口，都要转发）；
- 好友手机不需要装任何软件、不需要 root；FCL 本身即启动器。

---

## 七、排障

| 现象 | 原因与处理 |
|---|---|
| edge 日志报 `supernode ... not responding` | 服务器 UDP 端口没通：查云安全组 + 系统防火墙 + `ss -ulnp` |
| 双方都“已连接”但 ping 不通 | 网段/密钥不一致；或 MTU 问题，试在设置里把 MTU 改 1200 |
| 延迟偏高 | 说明 P2P 打洞失败走了服务器中转（NAT 严格型），可换服务器地域更近；`-S` 系列参数禁用 |
| MC 看不到对方世界 | 版本不一致；或关掉组播依赖，用“直接连接 填 虚拟IP:端口” |
| 驱动安装失败 | 手动运行 `client/driver/tap-windows/9.24.7.exe` 安装 |
| 换房间后 IP 冲突 | 手动把虚拟 IP 改成网段内未被占用的值（如 .3/.4） |

---

## 八、官网访问统计后台（可选）

官网（GitHub Pages 发布）默认打点到**你自己的服务器**上的统计服务，访问数据不进任何第三方，带密码后台页可看今日/累计访问与独立访客。

### 1. 部署统计服务（服务器上）

把 `server/visit_stats.exe` 和 `server/start_stats.bat` 放到服务器同一目录，双击 `start_stats.bat` 即后台运行（Windows；Linux 服务器用 `python3 visit_stats.py`）。首次运行自动生成 `stats_config.json`，可修改 `admin_key`（后台密码）与 `port`（默认 8088），改后重启服务生效。

### 2. 防火墙与端口转发

- Windows 防火墙放行 TCP 8088 入站；
- 路由器把 TCP 8088 转发到服务器内网 IP（如 192.168.1.4）。

### 3. 后台地址（两种方式任选）

- **IPv4**：`http://你的公网IP:8088/admin?key=你的后台密码`（需路由器转发 TCP 8088）
- **IPv6（推荐，免转发）**：`http://[你的公网IPv6]:8088/admin?key=你的后台密码`
  —— 宽带支持 IPv6 时直接可用，**不需要路由器端口转发**（IPv6 每台设备都有公网地址）。IPv6 地址会随运营商变动，变化后需同步更新官网打点与徽章地址。

页面显示：今日 PV/UV、累计 PV/UV、最近 7 天、最近 30 条访问记录（时间/IP/页面/UA）。

### 4. 官网打点

官网打点脚本位于 `docs/index.html` 底部，**默认关闭**（源码里已留注释模板）。启用时把 `/hit` 地址改成你自己的统计服务地址即可——注意**不要**把含密钥的后台地址（`admin?key=...`）写进公开网页；打点端点 `/hit` 本身无需密钥。IPv6 地址用方括号 `[]` 包裹，推送后 Pages 自动重新部署。

### 5. 关闭统计

任务管理器结束 `visit_stats.exe`；彻底移除则删除 `visits.db`（统计数据）与 `stats_config.json`（配置）。

---

## 九、IPv6 免端口转发直连（主推，无需公网 IPv4）

家用宽带没有公网 IPv4、路由器端口转发做不通时，用 **IPv6 直连** 绕开路由器：IPv6 下每台设备都有公网地址，**不需要任何端口转发**。只要开房电脑和朋友的网络都有 IPv6（国内宽带/手机流量基本都支持），直接走这条方案。

> 实测结论：n2n 的 edge/supernode 的 `-l` 地址解析**只认 IPv4**（连官方 v3.1.1 也一样），IPv6 只能通过"本地转发器"接入。本项目已内置两段转发器，客户端工具**全自动**处理，你只需填 IPv6 地址。

### 1. 开房电脑（服务器）准备

1. 管理员运行 `server/start_supernode.bat` 启动 supernode（UDP 7654，自动放行防火墙）；
2. 再启动 IPv6 入口转发器（把公网 IPv6 的 7654 流量送进本机 supernode）：
   ```
   python server/udp6_forward.py
   ```
   （隐藏窗口常驻即可；或打包成 exe 后台运行。）
3. 查你的公网 IPv6 地址（发给朋友的就是这个）：
   ```
   ipconfig | findstr "IPv6"
   ```
   取 `2409:xxxx:...` 那行（形如 `2409:abcd:1234:…:xxxx`）。IPv6 是运营商分配的，重拨/重启可能变化，变了就重新查。

### 2. 客户端填法（每台电脑都装工具）

工具「服务器（公网 supernode）」栏直接填开房电脑的 IPv6 地址（**不带端口**，端口默认 7654）：

```
2409:abcd:1234:5678::1a2b   ← 换成你查到的自己的 IPv6
```

填完点「保存」→ 创建/加入房间即可。工具会自动：
- 检测到这是 IPv6 → 自动启动本地转发器（`bin/udp6_client_forward.exe`，监听 127.0.0.1:7655 起）；
- edge 连接本地转发器 → 经 IPv6 直连开房电脑的 supernode；
- 关房时自动清理转发器。

**房主自己**：工具识别到填的是本机 IPv6，会自动直连本机（`127.0.0.1:7654`），无需转发。

### 3. 验证

edge 日志出现以下即注册成功（工具状态区会显示"已连接"）：

```
[OK] edge <<< ================ >>> supernode
```

### 4. 注意事项

- **参与各方的网络都要有 IPv6**：朋友家没有 IPv6 的话，可让他先用 `https://test-ipv6.com` 自查；
- IPv6 地址会随网络重连变化，变了之后所有客户端都要改成新地址；
- 房间内成员注册成功后，n2n 会尝试双方 UDP 直连（IPv6 无 NAT，基本都能打洞成功），后续流量不再经过 supernode。

---

## 十、手机当 supernode（可选，实测有坑）

手机当 supernode 的**实测结论**：
- **Termux 直装版 n2n 与 lucktu arm64 静态包均被安卓 seccomp 拦截**（进程启动即被杀：`Unknown signal 31` / 退出码 159），**不可用**；
- **proot-distro Kali + `apt install n2n` 可以跑通**（`nohup supernode -p 7654 &` 可后台运行）；
- 但手机连 WiFi 是二级路由时**拿不到公网 IPv6**，无法作为 IPv6 节点；手机需要处于有公网 IPv6 的网络（如移动数据）才行。

因此**优先用第九章的电脑方案**；真要用手机当服务器时：

```
proot-distro login kali
apt update && apt install -y n2n
nohup supernode -p 7654 > /root/supernode.log 2>&1 &
```

注意：移植版 supernode **不支持 `-l` 管理端口参数**（会报 `invalid -l format`），只用 `-p 7654`；`deploy_supernode_android.sh` 为早期 Termux 版本，与实测可行路径不一致，仅供参考。

---

## 目录结构

```
n2n-lan/
├── README.md
├── LICENSE                   # 本仓库源码许可（MIT）
├── .gitignore
├── server/                      # 公网服务器端
│   ├── deploy_supernode.sh      #   Linux 一键部署（编译 + systemd + 防火墙）
│   ├── deploy_supernode_docker.sh
│   ├── deploy_supernode_android.sh  #   早期 Termux 一键部署（实测被安卓 seccomp 拦截，仅供参考）
│   ├── start_supernode.bat      #   Windows 服务器启动
│   ├── supernode.exe
│   ├── supernode_official_v311.exe #  官方 v3.1.1 交叉编译版 supernode（备用）
│   ├── udp6_forward.py          #   IPv6→IPv4 UDP 转发器（IPv6 免转发方案的服务端入口）
│   ├── supernode.service        #   systemd 模板
│   ├── visit_stats.py           #   官网访问统计服务源码（可选；或使用打包的 visit_stats.exe）
│   └── start_stats.bat          #   Windows 访问统计启动（可选）
└── client/                      # 客户端（Windows 整目录拷贝分发；macOS/Linux 源码运行）
    ├── start.bat                #   Windows 双击启动
    ├── start_mac.sh             #   macOS 启动（自检 + 引导安装）
    ├── install_mac.sh           #   macOS 一键部署（编译 edge + 装依赖 + 驱动指引）
    ├── make_mac_pkg.sh          #   macOS 客户端目录打包（可选）
    ├── n2n_room_manager.py      #   房间管理小工具（跨平台：Windows/macOS/Linux）
    ├── udp6_client_forward.py   #   IPv4→IPv6 UDP 转发器源码（客户端侧，Windows 自动调用 exe，其他平台调用本源码）
    ├── join_room_linux.sh       #   Linux 命令行进房脚本
    ├── bin/edge.exe             #   Windows: n2n v3.1.1 edge（官方源码交叉编译，支持 -E 等全部参数）
    ├── bin/edge                 #   macOS/Linux: edge（install_mac.sh 编译后生成）
    ├── bin/udp6_client_forward.exe # Windows: IPv6 本地转发器（工具自动启动/停止）
    ├── bin/supernode.exe        #   备用（本地开房调试用）
    ├── driver/tap-windows/      #   Windows: TAP 虚拟网卡驱动（tapinstall + 官方安装器）
    └── tools/WinIPBroadcast.exe #   Windows: 局域网发现广播助手（可选，仓库不提供）
```

## 开源与构建

- **源码许可**：本仓库自有代码（房间管理工具、部署脚本）采用 **MIT**（见 LICENSE）。
- **内置二进制许可**：`bin/edge.exe`、`bin/supernode.exe` 来自 n2n（**GPLv3**，github.com/ntop/n2n，
  lucktu 预编译版）；`driver/tap-windows/` 为 OpenVPN TAP 驱动组件（**GPLv2**）。再分发请遵守相应许可并保留来源声明。
- **WinIPBroadcast.exe 不随仓库分发**：该工具提取自 Bug侠 EasyN2N 包（bugxia.com），许可未明；
  需要广播助手时自行获取后放入 `client/tools/`（程序检测到文件存在即启用该功能，缺失时自动跳过）。
- **打包为免 Python 版 exe**（可选）：
  ```bash
  python -m PyInstaller --noconsole --onefile --name n2n_room_manager client/n2n_room_manager.py
  ```
  将生成的 `n2n_room_manager.exe` 与 `bin/`、`driver/`、`tools/` 同目录放置即可整包分发。
- **安全提醒**：`client/config.json` 含本机房间密钥/密码，已被 .gitignore 排除，请勿手动提交。

## 来源与致谢

- n2n 引擎 / Windows 二进制：github.com/ntop/n2n、github.com/lucktu/n2n
- TAP 驱动与广播工具：Bug侠 EasyN2N（bugxia.com），驱动为 OpenVPN Technologies 官方签名组件
- 环境受限时经 ghproxy.net 镜像获取 GitHub 文件
