import ipaddress
from ipaddress import ip_address

from fastapi import HTTPException, Request, status

def get_client_ip(request: Request):
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    else:
        return request.client.host if request.client else "0.0.0.0"

def _is_ip_in_networks(client_ip: ipaddress.IPv4Address | ipaddress.IPv6Address, rules: list[str]):
    for rule in rules:
        try:
            networks = ipaddress.ip_network(rule, strict=False)
        except ValueError:
            continue
        if client_ip in networks:
            return True
    return False

def enforce_ip_policy(request: Request, ip_whitelist: list[str] | None, ip_blacklist: list[str] | None):
    if not ip_whitelist and not ip_blacklist:
        return
    raw_ip = get_client_ip(request)
    try:
        client_ip = ipaddress.ip_address(raw_ip)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid client IP")
    if ip_blacklist and _is_ip_in_networks(client_ip, ip_blacklist):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP is blacklisted")
    if ip_whitelist and not _is_ip_in_networks(client_ip, ip_whitelist):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="IP is not whitelisted")