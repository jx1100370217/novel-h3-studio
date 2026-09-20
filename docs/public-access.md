# 公网访问

工作台默认只监听本机的 `127.0.0.1:8765`。公网网关由
`novel_h3.public_gateway` 提供密码保护，并监听 `8766`，不会直接暴露工作台
进程或 ComfyUI 端口。

## 固定地址：Tailscale Funnel

不需要购买域名。准备一台已安装 Tailscale 的机器，并用拥有该 Tailnet 的账号登录：

```bash
sudo tailscale up --hostname=novel-h3-workbench
```

首次使用 Funnel 时，在 Tailscale 控制台启用 Funnel，然后在项目根目录运行：

```bash
./scripts/install_public_access.sh
```

脚本会：

1. 安装并启用 `novel-h3-public-workbench.service`；
2. 关闭旧的临时 Cloudflare 隧道（如果存在）；
3. 将本地网关映射到 Tailscale Funnel；
4. 从 Tailscale 的 DNS 名称生成固定的 `https://<machine>.<tailnet>.ts.net/` 地址；
5. 将地址写入 `runtime/public-progress-address.txt`。

Tailscale 的 `tailscaled` 服务需要保持启用。工作台登录仍使用
`runtime/public-workbench-credentials.json` 中的账号密码；不要把该文件提交到 Git。

查看或关闭 Funnel：

```bash
sudo tailscale funnel status
sudo tailscale funnel --https=443 off
```

## 局域网备用地址

同一局域网内也可以直接访问服务器地址：

```text
http://<服务器局域网IP>:8766/
```

该地址只在局域网可用；跨互联网访问应使用 Tailscale Funnel 或自有 VPS 反向代理。
