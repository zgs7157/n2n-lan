# ============================================================
# n2n 官网部署到 Cloudflare Pages（免费）
# 用法（任选其一）：
#   1) 已登录： 先运行  npx wrangler login  完成浏览器授权
#      然后运行  powershell -ExecutionPolicy Bypass -File deploy_cloudflare.ps1
#   2) 有 token： 把下面 TOKEN 换成你的 API Token 再运行本脚本
# ============================================================

$ErrorActionPreference = "Stop"

$TOKEN = ""   # <-- 方式2：在这里粘贴 API Token（Edit Cloudflare Workers 模板）

if ($TOKEN) {
    $env:CLOUDFLARE_API_TOKEN = $TOKEN
    Write-Host "[1/2] 使用 API Token 认证" -ForegroundColor Cyan
} else {
    Write-Host "[1/2] 使用 wrangler 已保存的登录态（如未登录请先跑: npx wrangler login）" -ForegroundColor Cyan
}

$dist = Join-Path $PSScriptRoot "dist"
if (-not (Test-Path $dist)) {
    Write-Host "错误：找不到 dist 目录（$dist）" -ForegroundColor Red
    exit 1
}

Write-Host "[2/2] 部署到 Cloudflare Pages（项目名 n2n-lan，域名 n2n-lan.pages.dev）..." -ForegroundColor Cyan
npx -y wrangler@latest pages deploy $dist --project-name n2n-lan --commit-dirty=true

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "部署成功！访问地址：" -ForegroundColor Green
    Write-Host "  https://n2n-lan.pages.dev" -ForegroundColor Green
} else {
    Write-Host "部署失败，请检查上方错误信息。" -ForegroundColor Red
}
