#!/bin/bash
# 网络白名单防火墙 —— 默认拒绝,只放行项目需要的域名。
# 研究项目只需:币安公开转储 + S3 + PyPI + GitHub + Anthropic API
set -euo pipefail

ALLOWED_DOMAINS=(
    # 币安公开数据转储(CDN,不受地理封锁)
    "data.binance.vision"
    "s3.ap-northeast-1.amazonaws.com"
    "s3-ap-northeast-1.amazonaws.com"
    # 装 Python 依赖
    "pypi.org"
    "files.pythonhosted.org"
    # Claude Code 自身
    "api.anthropic.com"
    "github.com"
    "api.github.com"
    "registry.npmjs.org"
)

echo "[firewall] 重置规则..."
iptables -F
iptables -X 2>/dev/null || true
ipset destroy allowed 2>/dev/null || true

iptables -A INPUT  -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT  -m state --state ESTABLISHED,RELATED -j ACCEPT

iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

ipset create allowed hash:ip
for domain in "${ALLOWED_DOMAINS[@]}"; do
    echo "[firewall] 解析 $domain ..."
    ips=$(dig +short A "$domain" | grep -E '^[0-9.]+$' || true)
    if [ -z "$ips" ]; then
        echo "[firewall] 警告:$domain 没解析到 IP,跳过"
        continue
    fi
    for ip in $ips; do
        ipset add allowed "$ip" 2>/dev/null || true
    done
done

iptables -A OUTPUT -m set --match-set allowed dst -j ACCEPT

iptables -P INPUT DROP
iptables -P OUTPUT DROP
iptables -P FORWARD DROP

echo "[firewall] 完成。放行 ${#ALLOWED_DOMAINS[@]} 个域名,其余出站已拒绝。"
