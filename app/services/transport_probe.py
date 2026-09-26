"""
Temporary transport diagnostic module for production networking debugging.

This module provides isolated DNS/TCP/TLS/HTTP probes to diagnose
DuckDuckGo connectivity issues in Render production.

It runs once during FastAPI startup and logs results via the standard logger.
It does NOT modify any existing NORA behavior.
"""
from __future__ import annotations

import asyncio
import socket
import ssl
import time
from typing import List, Tuple, Optional, Dict, Any

from app.logging import logger


# User-Agent for HTTP requests - matches NORA's existing User-Agent
USER_AGENT = "NORAResearchBot/1.0 (+https://github.com/tmakiriyado1-arch/atis-node-builder)"

# Targets to probe
TARGETS = [
    {"host": "html.duckduckgo.com", "port": 443, "name": "DuckDuckGo"},
    {"host": "example.com", "port": 443, "name": "Control"},
]

# Bounded timeouts (seconds)
DNS_TIMEOUT = 5.0
TCP_TIMEOUT = 5.0
TLS_TIMEOUT = 5.0
HTTP_TIMEOUT = 10.0


def _elapsed_ms(start_time: float) -> int:
    """Calculate elapsed milliseconds from start time."""
    return int((time.time() - start_time) * 1000)


def _log_probe(message: str, **kwargs: Any) -> None:
    """Log a probe message with consistent prefix."""
    kwargs_str = " ".join(f"{k}={v}" for k, v in kwargs.items())
    if kwargs_str:
        logger.info(f"[TRANSPORT_PROBE] {message} {kwargs_str}")
    else:
        logger.info(f"[TRANSPORT_PROBE] {message}")


def probe_dns(host: str) -> Tuple[bool, List[Tuple[str, int, int]], Optional[str]]:
    """
    Stage 1: DNS resolution using socket.getaddrinfo().
    
    Returns:
        Tuple of (success, list of (ip, port, address_family), error_message)
    """
    start_time = time.time()
    _log_probe("DNS START", host=host)
    
    try:
        # Use getaddrinfo to get all address families
        addr_info = socket.getaddrinfo(
            host,
            443,
            proto=socket.IPPROTO_TCP,
        )
        
        # Extract unique IP addresses with their families
        # AF_INET = 2 (IPv4), AF_INET6 = 10 (IPv6)
        resolved: List[Tuple[str, int, int]] = []
        seen_ips: set[str] = set()
        
        for info in addr_info:
            ip = info[4][0]  # address
            port = info[4][1]  # port
            family = info[0]   # address family
            
            if ip not in seen_ips:
                seen_ips.add(ip)
                resolved.append((ip, port, family))
        
        elapsed = _elapsed_ms(start_time)
        family_str = ",".join(
            f"{ip}({'IPv4' if af == socket.AF_INET else 'IPv6'})"
            for ip, _, af in resolved
        )
        _log_probe(
            "DNS SUCCESS",
            host=host,
            elapsed_ms=elapsed,
            addresses=family_str,
            count=len(resolved),
        )
        return True, resolved, None
        
    except socket.gaierror as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "DNS FAILURE",
            host=host,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, [], str(e)
    except Exception as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "DNS FAILURE",
            host=host,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, [], str(e)


def probe_tcp(host: str, ip: str, family: int, port: int) -> Tuple[bool, Optional[str]]:
    """
    Stage 2: Raw TCP connection test.
    
    Returns:
        Tuple of (success, error_message)
    """
    start_time = time.time()
    family_str = "IPv4" if family == socket.AF_INET else "IPv6"
    _log_probe("TCP START", host=host, ip=ip, family=family_str)
    
    try:
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((ip, port))
        sock.close()
        
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TCP SUCCESS",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
        )
        return True, None
        
    except socket.timeout as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TCP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e)
    except ConnectionRefusedError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TCP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e)
    except OSError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TCP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e)
    except Exception as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TCP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e)


def probe_tls(host: str, ip: str, family: int, port: int) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Stage 3: TLS handshake using Python's ssl module.
    
    Returns:
        Tuple of (success, error_message, tls_info_dict)
    """
    start_time = time.time()
    family_str = "IPv4" if family == socket.AF_INET else "IPv6"
    _log_probe("TLS START", host=host, ip=ip, family=family_str)
    
    try:
        # Create a socket
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(TLS_TIMEOUT)
        
        # Wrap with SSL context
        context = ssl.create_default_context()
        # Set SNI hostname
        ssl_sock = context.wrap_socket(sock, server_hostname=host)
        
        # Connect
        ssl_sock.connect((ip, port))
        
        # Get certificate info
        cert = ssl_sock.getpeercert()
        version = ssl_sock.version()
        cipher = ssl_sock.cipher()
        
        ssl_sock.close()
        
        elapsed = _elapsed_ms(start_time)
        cipher_name = cipher[0] if cipher else "unknown"
        cipher_version = version if version else "unknown"
        
        _log_probe(
            "TLS SUCCESS",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            version=cipher_version,
            cipher=cipher_name,
        )
        
        # Extract cert info safely - cert fields are tuples of (key, value) pairs
        cert_subject = None
        cert_issuer = None
        if cert:
            try:
                raw_subject = cert.get("subject")
                if raw_subject:
                    cert_subject = [(s[0][0], s[0][1]) for s in raw_subject] if isinstance(raw_subject, list) else None
            except Exception:
                pass
            try:
                raw_issuer = cert.get("issuer")
                if raw_issuer:
                    cert_issuer = [(i[0][0], i[0][1]) for i in raw_issuer] if isinstance(raw_issuer, list) else None
            except Exception:
                pass
        
        tls_info = {
            "version": cipher_version,
            "cipher": cipher_name,
            "cert_subject": cert_subject,
            "cert_issuer": cert_issuer,
        }
        return True, None, tls_info
        
    except ssl.SSLError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TLS FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except socket.timeout as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TLS FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except ConnectionRefusedError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TLS FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except OSError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TLS FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except Exception as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "TLS FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None


async def probe_http(host: str, ip: str, family: int, port: int) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Stage 4: HTTP request using httpx (async).
    
    Returns:
        Tuple of (success, error_message, response_info_dict)
    """
    start_time = time.time()
    family_str = "IPv4" if family == socket.AF_INET else "IPv6"
    
    # Build URL
    url = f"https://{host}/"
    
    # For DuckDuckGo, use the actual search URL with the query
    if host == "html.duckduckgo.com":
        url = f"https://{host}/html/?q=African%20Development%20Bank"
    
    _log_probe("HTTP START", host=host, ip=ip, family=family_str, url=url)
    
    try:
        import httpx
        
        headers = {"User-Agent": USER_AGENT}
        
        async with httpx.AsyncClient(
            headers=headers,
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            
            elapsed = _elapsed_ms(start_time)
            status = response.status_code
            http_version = response.http_version
            
            # Extract relevant headers
            relevant_headers: Dict[str, str] = {}
            header_keys = ["server", "location", "content-type", "content-length"]
            for key in header_keys:
                val = response.headers.get(key)
                if val:
                    relevant_headers[key] = val
            
            # Get body preview safely
            body = response.text
            body_length = len(body)
            
            # Normalize whitespace for preview
            import re
            preview = re.sub(r'\s+', ' ', body[:400]).strip()[:200]
            
            _log_probe(
                "HTTP SUCCESS",
                host=host,
                ip=ip,
                family=family_str,
                elapsed_ms=elapsed,
                status=status,
                http_version=str(http_version),
            )
            
            # Log relevant headers
            if relevant_headers:
                headers_str = " ".join(f"{k}={v}" for k, v in relevant_headers.items())
                _log_probe(
                    "HTTP HEADERS",
                    host=host,
                    headers=headers_str,
                )
            
            # Log body preview
            _log_probe(
                "HTTP BODY PREVIEW",
                host=host,
                length=body_length,
                preview=preview,
            )
            
            response_info = {
                "status": status,
                "http_version": str(http_version),
                "headers": relevant_headers,
                "body_length": body_length,
                "body_preview": preview,
            }
            return True, None, response_info
            
    except httpx.TimeoutException as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "HTTP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except httpx.ConnectError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "HTTP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except httpx.HTTPStatusError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "HTTP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
            status_code=e.response.status_code,
        )
        return False, str(e), None
    except httpx.RequestError as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "HTTP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None
    except Exception as e:
        elapsed = _elapsed_ms(start_time)
        _log_probe(
            "HTTP FAILURE",
            host=host,
            ip=ip,
            family=family_str,
            elapsed_ms=elapsed,
            error_type=type(e).__name__,
            error=str(e),
        )
        return False, str(e), None


def run_dns_probes() -> Dict[str, Any]:
    """Run DNS probes for all targets. Returns results dict."""
    results: Dict[str, Any] = {}
    for target in TARGETS:
        host = target["host"]
        success, resolved, error = probe_dns(host)
        results[host] = {
            "dns": {"success": success, "resolved": resolved, "error": error}
        }
    return results


def run_tcp_probes(dns_results: Dict[str, Any]) -> Dict[str, Any]:
    """Run TCP probes for all resolved addresses. Returns updated results dict."""
    for host, data in dns_results.items():
        dns_info = data.get("dns", {})
        resolved = dns_info.get("resolved", [])
        data["tcp"] = []
        
        for ip, port, family in resolved:
            success, error = probe_tcp(host, ip, family, port)
            data["tcp"].append({
                "ip": ip,
                "family": "IPv4" if family == socket.AF_INET else "IPv6",
                "success": success,
                "error": error,
            })
    return dns_results


def run_tls_probes(tcp_results: Dict[str, Any]) -> Dict[str, Any]:
    """Run TLS probes for successful TCP connections. Returns updated results dict."""
    for host, data in tcp_results.items():
        dns_info = data.get("dns", {})
        tcp_info = data.get("tcp", [])
        data["tls"] = []
        
        for tcp_result in tcp_info:
            if tcp_result.get("success"):
                ip = tcp_result["ip"]
                family = socket.AF_INET if tcp_result["family"] == "IPv4" else socket.AF_INET6
                success, error, tls_info = probe_tls(host, ip, family, 443)
                data["tls"].append({
                    "ip": ip,
                    "family": tcp_result["family"],
                    "success": success,
                    "error": error,
                    "info": tls_info,
                })
    return tcp_results


async def run_http_probes(tls_results: Dict[str, Any]) -> Dict[str, Any]:
    """Run HTTP probes for successful TLS connections. Returns updated results dict.
    
    For each host, only test HTTP once using the first successful TLS connection
    to avoid redundant requests.
    """
    for host, data in tls_results.items():
        tls_info = data.get("tls", [])
        data["http"] = []
        
        # Find first successful TLS result for this host
        first_success = None
        for tls_result in tls_info:
            if tls_result.get("success"):
                first_success = tls_result
                break
        
        if first_success:
            ip = first_success["ip"]
            family = socket.AF_INET if first_success["family"] == "IPv4" else socket.AF_INET6
            success, error, http_info = await probe_http(host, ip, family, 443)
            data["http"].append({
                "ip": ip,
                "family": first_success["family"],
                "success": success,
                "error": error,
                "info": http_info,
            })
    return tls_results


async def run_full_probe() -> Dict[str, Any]:
    """
    Run the complete diagnostic probe sequence.
    
    This is the main entry point called during application startup.
    It runs all stages: DNS -> TCP -> TLS -> HTTP.
    
    Returns:
        Complete results dictionary.
    """
    _log_probe("PROBE START")
    
    # Stage 1: DNS (synchronous)
    dns_results = run_dns_probes()
    
    # Stage 2: TCP (synchronous)
    tcp_results = run_tcp_probes(dns_results)
    
    # Stage 3: TLS (synchronous)
    tls_results = run_tls_probes(tcp_results)
    
    # Stage 4: HTTP (async)
    http_results = await run_http_probes(tls_results)
    
    _log_probe("PROBE COMPLETE")
    
    return http_results


def run_probe_sync() -> None:
    """
    Synchronous wrapper for the probe that can be called from sync contexts.
    
    This creates an async event loop and runs the full probe.
    Used when we need to run the probe from a synchronous startup hook.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(run_full_probe())
    except Exception as e:
        _log_probe(
            "PROBE EXCEPTION",
            error_type=type(e).__name__,
            error=str(e),
        )
    finally:
        try:
            loop.close()
        except Exception:
            pass
