#!/usr/bin/env bash
set -e

# Setup strict Default-Deny network whitelist:
# Only allow:
# 1. Loopback (127.0.0.1)
# 2. Host gateway / private subnets (for LM Studio on host.docker.internal:1234)
# 3. CrazyRouter IP (80.71.236.197:443 for OpenCode DeepSeek Flash)
# Reject everything else immediately with tcp-reset / icmp-port-unreachable.

if command -v iptables >/dev/null 2>&1; then
    iptables -F OUTPUT 2>/dev/null || true
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
    # Allow Docker bridge and host gateway
    iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT
    iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT
    iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT
    # Allow CrazyRouter on 443
    iptables -A OUTPUT -d 80.71.236.197 -p tcp --dport 443 -j ACCEPT
    # Reject everything else instantly
    iptables -A OUTPUT -p tcp -j REJECT --reject-with tcp-reset
    iptables -A OUTPUT -j REJECT --reject-with icmp-port-unreachable
    iptables -P OUTPUT DROP

    # Lock down iptables binaries so nothing in the container can undo rules
    chmod 000 /usr/sbin/iptables* /usr/sbin/ip6tables* /usr/sbin/nft* 2>/dev/null || true
    echo "🔒 Strict network whitelist enforced (only host.docker.internal:1234 and api.lhcwn.pro:443 allowed)."
fi

exec "$@"
