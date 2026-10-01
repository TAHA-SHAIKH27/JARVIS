"""
J.A.R.V.I.S. network diagnostics — single source of truth for connectivity state.

Distinguishes the cases users actually hit, instead of one generic
"network issue communicating with my neural processors":

  1. wifi_off / no_adapter   — no active Wi-Fi/Ethernet (airplane mode,
                               Wi-Fi switch off, cable unplugged). No
                               non-loopback interface is UP.
  2. disconnected            — adapter exists but has no usable IPv4
                               (169.254.x.x link-local only, or DHCP failed).
  3. local_only              — joined a router / LAN (private IP) but the
                               router itself has no WAN (ISP down, router
                               unplugged from internet, captive portal).
  4. no_dns                 — basic IP routing works but DNS resolution fails
                               (DNS hijack, restrictive firewall, bad DNS).
  5. gemini_unreachable       — internet works, but Google's Generative
                               Language endpoint can't be reached (Google
                               outage, ISP/SNI block, corporate firewall,
                               VPN/proxy issue).
  6. online                  — everything reachable.

No third-party deps: stdlib + psutil (already a project dependency).
All probes use short timeouts and results are cached ~10s so error-path
diagnostics never stall Jarvis for long.
"""
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request

_CACHE = {"snapshot": None, "ts": 0.0}
CACHE_TTL = 10.0

GEMINI_HOST = "generativelanguage.googleapis.com"
GEMINI_PROBE_URL = f"https://{GEMINI_HOST}/"
DNS_TEST_HOST = GEMINI_HOST
INTERNET_TEST_ADDR = ("8.8.8.8", 53)


def _get_interfaces():
    """Return {name: {'addrs': [ipv4...], 'up': bool}} for non-loopback NICs."""
    import psutil
    info = {}
    try:
        stats = psutil.net_if_stats()
    except Exception:
        stats = {}
    try:
        addrs = psutil.net_if_addrs()
    except Exception:
        return info
    for name, addr_list in addrs.items():
        ipv4s = [
            a.address for a in addr_list
            if getattr(a.family, "name", "") == "AF_INET" or a.family == socket.AF_INET
        ]
        # Drop loopback-only interfaces
        non_loop = [ip for ip in ipv4s if not ip.startswith("127.")]
        if not non_loop:
            continue
        is_up = True
        try:
            if name in stats:
                is_up = bool(stats[name].isup)
        except Exception:
            pass
        info[name] = {"addrs": non_loop, "up": is_up}
    return info


def _is_link_local(ip: str) -> bool:
    return ip.startswith("169.254.")


def _is_private_ip(ip: str) -> bool:
    try:
        parts = [int(p) for p in ip.split(".")]
        if len(parts) != 4:
            return False
        if parts[0] == 10:
            return True
        if parts[0] == 172 and 16 <= parts[1] <= 31:
            return True
        if parts[0] == 192 and parts[1] == 168:
            return True
        return False
    except Exception:
        return False


def get_wifi_ssid() -> str:
    """Best-effort current Wi-Fi SSID (Windows netsh / Linux iwgetid)."""
    try:
        # Windows
        out = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=4,
        )
        if out.returncode == 0 and out.stdout:
            m = re.search(r"^\s*SSID\s*:\s*(.+?)\s*$", out.stdout, re.M | re.I)
            if m:
                ssid = m.group(1).strip()
                if ssid and ssid.lower() not in ("", "none"):
                    return ssid
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return ""


def _check_internet(timeout: float = 2.0) -> bool:
    """Can we route to the open internet? (TCP to 8.8.8.8:53 — no DNS needed)."""
    try:
        s = socket.create_connection(INTERNET_TEST_ADDR, timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _check_dns(timeout: float = 3.0) -> bool:
    try:
        old = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            socket.gethostbyname(DNS_TEST_HOST)
            return True
        finally:
            socket.setdefaulttimeout(old)
    except Exception:
        return False


def _check_gemini_reachable(timeout: float = 4.0) -> bool:
    """Is Google's API edge reachable? Any HTTP response (even 4xx) = reachable."""
    try:
        req = urllib.request.Request(GEMINI_PROBE_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        # Server answered (404/403/...) — network path is fine.
        return True
    except Exception:
        return False


def get_connectivity_snapshot(force: bool = False) -> dict:
    """Probe NICs -> internet -> DNS -> Gemini. Cached for CACHE_TTL seconds."""
    now = time.time()
    if not force and _CACHE["snapshot"] and (now - _CACHE["ts"] < CACHE_TTL):
        return _CACHE["snapshot"]

    interfaces = _get_interfaces()
    up_ifaces = {k: v for k, v in interfaces.items() if v["up"]}
    all_ips = [ip for v in up_ifaces.values() for ip in v["addrs"]]
    usable_ips = [ip for ip in all_ips if not _is_link_local(ip)]

    ssid = get_wifi_ssid() if up_ifaces else ""

    snap = {
        "interfaces": interfaces,
        "up_interfaces": list(up_ifaces.keys()),
        "local_ips": usable_ips,
        "ssid": ssid,
        "internet": False,
        "dns": False,
        "gemini_reachable": False,
        "state": "wifi_off",
    }

    if not up_ifaces:
        snap["state"] = "wifi_off"
    elif not usable_ips:
        snap["state"] = "disconnected"
    else:
        snap["internet"] = _check_internet()
        if not snap["internet"]:
            snap["state"] = "local_only"
        else:
            snap["dns"] = _check_dns()
            if not snap["dns"]:
                snap["state"] = "no_dns"
            else:
                snap["gemini_reachable"] = _check_gemini_reachable()
                snap["state"] = "online" if snap["gemini_reachable"] else "gemini_unreachable"

    _CACHE["snapshot"] = snap
    _CACHE["ts"] = now
    return snap


def _reason_text(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    parts = [str(exc)]
    if reason is not None and str(reason) not in str(exc):
        parts.append(str(reason))
    return " | ".join(p for p in parts if p)


def classify_exception(exc: BaseException) -> str:
    """Map a Gemini-call exception onto one of the snapshot states (hint)."""
    txt = _reason_text(exc).lower()
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"  # creds/quota/model — NOT a network problem
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    # Classic offline markers from WinSock / getaddrinfo / urllib
    if any(k in txt for k in (
        "getaddrinfo failed", "name or service not known", "nodename nor servname",
        "temporary failure in name resolution", "11001", "11002", "[errno 8]",
    )):
        return "no_dns"
    if any(k in txt for k in (
        "network is unreachable", "no route to host", "10051", "10065",
        "network is down", "10050", "errno 101", "errno 51",
    )):
        return "local_only"
    if any(k in txt for k in (
        "connection refused", "connection reset", "10061", "10054",
        "ssl", "certificate", "handshake", "proxy", "tunnel",
    )):
        return "gemini_unreachable"
    if isinstance(exc, (urllib.error.URLError, OSError, ConnectionError)):
        return "no_internet_generic"
    return "unknown"


STATE_LABELS = {
    "wifi_off": "Wi-Fi / network adapter off",
    "disconnected": "Not joined to any network",
    "local_only": "Connected to router, no internet",
    "no_dns": "Connected, DNS failing",
    "gemini_unreachable": "Internet OK, Google unreachable",
    "online": "Online",
}


def build_jarvis_message(snapshot: dict | None = None,
                         exc: BaseException | None = None,
                         mode: str = "chat") -> str:
    """Jarvis-persona speak text for the current connectivity reality.

    mode: "chat" (free conversation, no offline fallback),
          "command" (we will ALSO run the local offline parser),
          "vision"/"document" (needs upload + cloud reasoning).
    """
    snap = snapshot or get_connectivity_snapshot()
    state = snap.get("state", "wifi_off")
    ssid = snap.get("ssid", "")
    ips = snap.get("local_ips", [])
    ip_str = ips[0] if ips else "none"
    where = f" ({ssid}, {ip_str})" if ssid else (f" ({ip_str})" if ip_str != "none" else "")

    exc_hint = classify_exception(exc) if exc is not None else ""
    local_note = (" I can still handle offline tasks — system controls, files, "
                  "timers, notes — just say the word, sir.") if mode == "command" else ""
    if mode in ("vision", "document"):
        local_note = ""

    if state == "wifi_off":
        return ("My wireless uplink appears to be completely down, sir — no active "
                "Wi-Fi or Ethernet adapter detected. Please check the Wi-Fi switch, "
                "airplane mode, or the cable, then try again." + local_note)
    if state == "disconnected":
        return ("I'm not joined to any network, sir — the adapter is up but has no "
                "valid IP address. Please connect to a Wi-Fi network first." + local_note)
    if state == "local_only":
        return (f"I'm latched onto your local network{where}, sir, but the router "
                "itself has no internet — pages won't load anywhere. Please check the "
                "router's WAN light, reboot it, or confirm the ISP isn't down." + local_note)
    if state == "no_dns":
        return ("I'm connected to the internet, sir, but name resolution is failing — "
                "I can't turn addresses like Google's into IPs. Try switching DNS to "
                "8.8.8.8, disabling any VPN or custom DNS filter, then retry." + local_note)
    if state == "gemini_unreachable":
        if exc_hint == "timeout":
            return ("Your connection is up, sir, but Google's neural core is taking too "
                    "long to answer — likely congestion or a slow link. I've timed out; "
                    "please try again in a moment." + local_note)
        return ("Your internet is working, sir, but I cannot reach Google's neural core — "
                "possibly a Google outage, firewall, or ISP block on googleapis.com. "
                "Check https://status.cloud.google.com, pause any VPN/firewall, then retry."
                + local_note)
    # state == "online" but the call still failed -> transient blip or HTTP error
    if isinstance(exc, urllib.error.HTTPError):
        return (f"Communication error with my neural processors (HTTP {exc.code}), sir.")
    if exc_hint == "timeout":
        return ("The request timed out, sir — the network is up but Google was slow to "
                "answer. Please try again." + local_note)
    return ("I hit a brief network wobble reaching my neural processors, sir — your "
            "connection looks fine otherwise. Please try again." + local_note)
