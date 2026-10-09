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
   sudo bash join_room_linux.sh '房间码' 482913 39.162.81.68:7654
   sudo bash join_room_linux.sh '房间码' 39.162.81.68:7654
   ```
   （raw.githubusercontent 直连不通时，给 wget 加 ghproxy 前缀：
   `https://ghproxy.net/https://raw.githubusercontent.com/...`）
3. MC 多人游戏 → 直接连接 → 填 `10.x.0.1:25565`。

> 注意：n2n 客户端必须为 **v3**（与服务器协议一致）。脚本会创建虚拟网卡 `n2n0`，需要 root；退出房间按脚本结尾提示清理。

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
3. 保存生效后，所有客户端（含你）把 supernode 填成 **你的公网 IPv4:7654**（用 `https://myip.ipip.net` 查询当前值，如 `39.162.81.68:7654`）。
4. 注意：家庭宽带公网 IP 可能随重拨变化，长期使用建议在路由器里配置 DDNS 域名，或用域名代替 IP。
- 本机 Windows 防火墙放行由 `start_supernode.bat` 自动完成（UDP 7654 入站）。

### 方式二：公共 supernode（无公网 IP / 路由器改不了时的备用）
改用社区维护的公共 n2n supernode（如 Bug侠/EasyN2N 的 bj/cd/sh/gz 节点），**所有人填同一个公共节点地址**即可：
- 房间隔离仍由「房间码 = community@网段#密钥」保证，密钥即传输加密口令；
- 代价：不经过自己的服务器，依赖公共节点可用性与延迟。
- 公共节点地址获取：访问 bugxia.com 的 N2N 页面或 EasyN2N 使用文档。

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

## 目录结构

```
n2n-lan/
├── README.md
├── LICENSE                   # 本仓库源码许可（MIT）
├── .gitignore
├── server/                      # 公网服务器端
│   ├── deploy_supernode.sh      #   Linux 一键部署（编译 + systemd + 防火墙）
│   ├── deploy_supernode_docker.sh
│   ├── start_supernode.bat      #   Windows 服务器启动
│   ├── supernode.exe
│   └── supernode.service        #   systemd 模板
└── client/                      # Windows 客户端（整目录拷贝分发）
    ├── start.bat                #   双击启动
    ├── n2n_room_manager.py      #   房间管理小工具
    ├── bin/edge.exe             #   n2n v3.1.1 edge（lucktu 编译）
    ├── driver/tap-windows/      #   TAP 虚拟网卡驱动（tapinstall + 官方安装器）
    └── tools/WinIPBroadcast.exe #   局域网发现广播助手（可选，仓库不提供）
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
