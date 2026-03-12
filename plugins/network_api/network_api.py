"""
Network API detection plugin.
Identifies networking function calls (sockets, HTTP, DNS) to flag
potential C2 communication, data exfiltration, or downloader behaviour.
"""

NETWORK_APIS = {
    # BSD sockets
    "socket": "socket_create",
    "connect": "socket_connect",
    "bind": "socket_bind",
    "listen": "socket_listen",
    "accept": "socket_accept",
    "send": "socket_send",
    "recv": "socket_recv",
    "sendto": "socket_sendto",
    "recvfrom": "socket_recvfrom",
    "select": "socket_multiplex",
    # Windows sockets
    "wsastartup": "winsock_init",
    "wsasocketa": "winsock_create",
    "wsasocketw": "winsock_create",
    "wsaconnect": "winsock_connect",
    # HTTP / WinINet / WinHTTP
    "internetopena": "wininet_open",
    "internetopenw": "wininet_open",
    "internetopenurla": "wininet_url",
    "internetopenurlw": "wininet_url",
    "httpopena": "winhttp_open",
    "httpopenw": "winhttp_open",
    "httpsendrequesta": "winhttp_send",
    "httpsendrequestw": "winhttp_send",
    "internetreadfile": "wininet_read",
    "winhttp": "winhttp_generic",
    # DNS
    "gethostbyname": "dns_resolve",
    "getaddrinfo": "dns_resolve",
    "dnsquery_a": "dns_query",
    "dnsquery_w": "dns_query",
    # URL download
    "urldownloadtofile": "url_download",
    "urldownloadtofilea": "url_download",
    "urldownloadtofilew": "url_download",
}


def analyze(graph_store, func_addr: int) -> dict:
    """Detect network API usage in a function."""
    blocks = graph_store.fetch_basic_blocks(func_addr)
    if not blocks:
        return {}

    findings = []

    for bb in blocks:
        insns = graph_store.fetch_block_instructions(bb)
        for insn in insns:
            mnem = (insn.get("mnemonic") or "").lower()
            if mnem not in ("call", "bl", "blr"):
                continue
            ops = insn.get("operands") or []
            for op in ops:
                if not isinstance(op, str):
                    continue
                normalised = op.lower().replace("_", "")
                for api_name, category in NETWORK_APIS.items():
                    if api_name in normalised:
                        findings.append({
                            "type": "network_api",
                            "addr": insn.get("addr"),
                            "api": op,
                            "category": category,
                        })
                        break

    return {"network": findings} if findings else {}
