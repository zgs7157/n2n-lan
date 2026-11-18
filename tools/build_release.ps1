# n2n-lan 1.2.1 打包流水线（本机执行）
# 用法：pwsh -File tools\build_release.ps1
$ErrorActionPreference = "Stop"
$root = "D:\N2N\n2n-lan"
$client = Join-Path $root "client"
$dist   = Join-Path $root "build_tmp\dist"
$work   = Join-Path $root "build_tmp\work"
$spec   = Join-Path $root "build_tmp"
$icon   = Join-Path $client "n2n-lan.ico"
$verFile = Join-Path $root "tools\version_info.txt"
$py = "C:\Python314\python.exe"
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
$setupName = "n2n-lan-setup-1.2.1.exe"

New-Item -ItemType Directory -Force -Path $dist | Out-Null

Write-Host "== 0/7 编译 IPv6 转发器（含 --server 服务端模式）=="
& $py -m PyInstaller --onefile --noconsole --clean --noconfirm `
  --distpath (Join-Path $root "build_tmp\dist_fw") --workpath (Join-Path $root "build_tmp\work_fw") --specpath $spec `
  --name udp6_client_forward `
  --exclude-module numpy --exclude-module PIL --exclude-module pyzbar --exclude-module scipy `
  (Join-Path $client "udp6_client_forward.py") | Out-Null
$fw = Join-Path $root "build_tmp\dist_fw\udp6_client_forward.exe"
if (-not (Test-Path -LiteralPath $fw)) { throw "转发器编译失败" }
Copy-Item -LiteralPath $fw -Destination (Join-Path $client "bin\udp6_client_forward.exe") -Force
Write-Host ("forwarder ok: {0} bytes" -f (Get-Item -LiteralPath $fw).Length)

Write-Host "== 1/7 PyInstaller 打包主程序 =="
& $py -m PyInstaller --onefile --noconsole --clean --noconfirm `
  --icon $icon --version-file $verFile `
  --distpath $dist --workpath $work --specpath $spec `
  --name n2n_room_manager `
  --exclude-module numpy --exclude-module PIL --exclude-module pyzbar --exclude-module scipy `
  (Join-Path $client "n2n_room_manager.py") | Out-Null

$exe = Join-Path $dist "n2n_room_manager.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "打包失败：exe 不存在" }
Start-Sleep -Seconds 5
if (-not (Test-Path -LiteralPath $exe)) { throw "打包后 exe 被删除（安全软件拦截）" }
$exeSize = (Get-Item -LiteralPath $exe).Length
Write-Host ("exe ok: {0} bytes" -f $exeSize)

Write-Host "== 2/7 安装到 client 目录 =="
Copy-Item -LiteralPath $exe -Destination (Join-Path $client "n2n_room_manager.exe") -Force
Start-Sleep -Seconds 3
if (-not (Test-Path -LiteralPath (Join-Path $client "n2n_room_manager.exe"))) { throw "复制到 client 后被删除（安全软件拦截）" }

Write-Host "== 3/7 启动存活检查 =="
$proc = Start-Process -FilePath (Join-Path $client "n2n_room_manager.exe") -WorkingDirectory $client -PassThru
Start-Sleep -Seconds 7
if ($proc.HasExited) { throw "客户端启动后退出，退出码 $($proc.ExitCode)" }
Write-Host ("alive pid={0} title={1}" -f $proc.Id, (Get-Process -Id $proc.Id).MainWindowTitle)
Stop-Process -Id $proc.Id -Force

Write-Host "== 4/7 绿色版 zip =="
& $py (Join-Path $root "make_client_zip.py")
$zip = Join-Path $root "n2n-lan-client.zip"
Copy-Item -LiteralPath $zip -Destination (Join-Path $root "docs\downloads\n2n-lan-client.zip") -Force
$zipSize = (Get-Item -LiteralPath $zip).Length
Write-Host ("zip ok: {0} bytes" -f $zipSize)

Write-Host "== 5/7 编译安装包 =="
Push-Location $root
& $iscc (Join-Path $root "setup_n2n.iss")
Pop-Location
$setup = Join-Path $root ("dist_installer\" + $setupName)
if (-not (Test-Path -LiteralPath $setup)) { throw "安装包未生成" }
Copy-Item -LiteralPath $setup -Destination (Join-Path $root ("docs\downloads\" + $setupName)) -Force
if (-not (Test-Path -LiteralPath (Join-Path $root ("docs\downloads\" + $setupName)))) { throw "安装包复制后被删除" }
$setupSize = (Get-Item -LiteralPath $setup).Length
$setupSha = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLower()

Write-Host "== 6/7 结果 =="
Write-Host ("setup  : {0} bytes  sha256={1}" -f $setupSize, $setupSha)
Write-Host ("zip    : {0} bytes" -f $zipSize)
Write-Host ("exe    : {0} bytes" -f $exeSize)
