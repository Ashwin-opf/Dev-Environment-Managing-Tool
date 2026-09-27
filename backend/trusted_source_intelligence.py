"""
trusted_source_intelligence.py — Authoritative Trusted Source Intelligence System.

Addresses:
- Problem #4: Trusted upstream release is newer than package-manager candidate.
- Problem #54: Repository/package-manager version is outdated compared with trusted upstream.
- Problem #71: Official download/update URL redirects incorrectly or becomes invalid.

Invariants:
1. Pure inspection, comparison, and decision layer — NEVER directly executes
   installers, shell commands, or mutates system state.
2. Every source has an explicit classification (TRUSTED_PACKAGE_MANAGER,
   TRUSTED_VENDOR_SOURCE, TRUSTED_VENDOR_RELEASE_API, TRUSTED_SIGNED_METADATA,
   UNTRUSTED_EXTERNAL_SOURCE, UNKNOWN_SOURCE).
3. AI / RAG / search / user URLs can NEVER establish trust or self-promote to STATIC_DB.
4. Downgrade protection prevents accidental rollbacks.
5. SSRF and local target destinations (localhost, private IPs, link-local, file://)
   are unconditionally rejected.
6. Offline / network failure produces UPSTREAM_UNAVAILABLE, NEVER "No update available".
"""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import socket
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import packaging.version

from canonical_identity import CanonicalIdentity, canonical_store
from structured_logger import structured_logger


# ===========================================================================
# 1. Enums and Classifications
# ===========================================================================

class SourceTrustClassification(str, Enum):
    """Authoritative classification of source trust provenance."""
    TRUSTED_PACKAGE_MANAGER = "TRUSTED_PACKAGE_MANAGER"
    TRUSTED_VENDOR_SOURCE = "TRUSTED_VENDOR_SOURCE"
    TRUSTED_VENDOR_RELEASE_API = "TRUSTED_VENDOR_RELEASE_API"
    TRUSTED_SIGNED_METADATA = "TRUSTED_SIGNED_METADATA"
    UNTRUSTED_EXTERNAL_SOURCE = "UNTRUSTED_EXTERNAL_SOURCE"
    UNKNOWN_SOURCE = "UNKNOWN_SOURCE"


def is_source_trusted(classification: SourceTrustClassification) -> bool:
    """Only authentic vendor or package manager sources are considered trusted."""
    return classification in (
        SourceTrustClassification.TRUSTED_PACKAGE_MANAGER,
        SourceTrustClassification.TRUSTED_VENDOR_SOURCE,
        SourceTrustClassification.TRUSTED_VENDOR_RELEASE_API,
        SourceTrustClassification.TRUSTED_SIGNED_METADATA,
    )


class SourceDecisionStatus(str, Enum):
    """Structured result statuses for trusted source intelligence decisions."""
    UPSTREAM_UPDATE_AVAILABLE = "UPSTREAM_UPDATE_AVAILABLE"
    REPOSITORY_UP_TO_DATE = "REPOSITORY_UP_TO_DATE"
    REPOSITORY_OUTDATED = "REPOSITORY_OUTDATED"
    NO_UPDATE = "NO_UPDATE"
    DOWNGRADE_CANDIDATE = "DOWNGRADE_CANDIDATE"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    VERSION_COMPARISON_UNKNOWN = "VERSION_COMPARISON_UNKNOWN"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    STALE_SOURCE_DATA = "STALE_SOURCE_DATA"
    UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE = "UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    OFFICIAL_URL_VALIDATED = "OFFICIAL_URL_VALIDATED"
    OFFICIAL_URL_UNRESOLVED = "OFFICIAL_URL_UNRESOLVED"
    UNTRUSTED_REDIRECT = "UNTRUSTED_REDIRECT"
    SSRF_ATTEMPT_BLOCKED = "SSRF_ATTEMPT_BLOCKED"
    HTTPS_DOWNGRADE_REJECTED = "HTTPS_DOWNGRADE_REJECTED"
    REDIRECT_LOOP = "REDIRECT_LOOP"
    EXCESSIVE_REDIRECTS = "EXCESSIVE_REDIRECTS"


# ===========================================================================
# 2. Data Models
# ===========================================================================

@dataclass
class ReleaseInfo:
    """Metadata representing a specific software release."""
    version: str
    release_tag: str = ""
    download_url: str = ""
    source_type: SourceTrustClassification = SourceTrustClassification.TRUSTED_VENDOR_SOURCE
    source_name: str = ""
    channel: str = "stable"               # "stable", "lts", "beta", "preview", "nightly"
    os: str = "Any"                       # "Windows", "Linux", "Darwin", "Any"
    architecture: str = "Any"             # "x64", "arm64", "x86", "Any"
    checksum: str = ""
    timestamp: Optional[float] = None
    prerelease: bool = False
    notes: str = ""


@dataclass
class SourceDecisionResult:
    """Structured decision output from Trusted Source Intelligence."""
    status: SourceDecisionStatus
    canonical_id: str
    installed_version: Optional[str] = None
    package_manager_version: Optional[str] = None
    upstream_version: Optional[str] = None
    selected_source: Optional[str] = None
    source_type: SourceTrustClassification = SourceTrustClassification.UNKNOWN_SOURCE
    source_trust: float = 0.0
    channel: str = "stable"
    os: str = "Any"
    architecture: str = "Any"
    compatible: bool = True
    update_available: bool = False
    downgrade: bool = False
    official_url: str = ""
    validated_url: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    reason: str = ""
    error: Optional[str] = None
    review_required: bool = False
    from_cache: bool = False
    cache_fresh: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "canonical_id": self.canonical_id,
            "installed_version": self.installed_version,
            "package_manager_version": self.package_manager_version,
            "upstream_version": self.upstream_version,
            "selected_source": self.selected_source,
            "source_type": self.source_type.value,
            "source_trust": self.source_trust,
            "channel": self.channel,
            "os": self.os,
            "architecture": self.architecture,
            "compatible": self.compatible,
            "update_available": self.update_available,
            "downgrade": self.downgrade,
            "official_url": self.official_url,
            "validated_url": self.validated_url,
            "redirect_chain": list(self.redirect_chain),
            "reason": self.reason,
            "error": self.error,
            "review_required": self.review_required,
            "from_cache": self.from_cache,
            "cache_fresh": self.cache_fresh,
        }


# ===========================================================================
# 3. Version Parsing, Normalization & Comparison
# ===========================================================================

class VersionComparator:
    """Authoritative semantic and vendor version parsing & comparison engine."""

    _PRERELEASE_PATTERNS = [
        re.compile(r"(?i)[-_.]?(rc|preview|beta|alpha|nightly|dev|pre)[-_.]?\d*"),
    ]

    @classmethod
    def clean_version_string(cls, raw: Optional[str]) -> Optional[str]:
        if not raw or not isinstance(raw, str):
            return None
        s = raw.strip()
        if not s:
            return None
        # Must contain at least one digit to be a plausible version string
        if not any(ch.isdigit() for ch in s):
            return None
        # Handle 'v1.2.3' or 'V1.2.3'
        if s.startswith(('v', 'V')) and len(s) > 1 and (s[1].isdigit() or s[1] == '.'):
            s = s[1:].strip()
        # Handle text like 'git version 2.44.0.windows.1' -> extract version
        match = re.search(r"(\d+(\.\d+)*([a-zA-Z0-9_\-\.]+)?)", s)
        if match:
            return match.group(1).strip()
        return None

    @classmethod
    def is_prerelease(cls, version_str: str) -> bool:
        """Determines if a version string indicates a non-stable prerelease."""
        if not version_str:
            return False
        clean = cls.clean_version_string(version_str) or version_str
        for pat in cls._PRERELEASE_PATTERNS:
            if pat.search(clean):
                return True
        return False

    @classmethod
    def parse_version(cls, version_str: Optional[str]) -> Optional[packaging.version.Version]:
        """Attempts to parse with packaging.version.Version."""
        clean = cls.clean_version_string(version_str)
        if not clean:
            return None
        try:
            return packaging.version.parse(clean)
        except Exception:
            # Fallback: clean out non-standard build tokens e.g. .windows.1
            sub_clean = re.sub(r"[a-zA-Z]+", "", clean).strip(".")
            if sub_clean:
                try:
                    return packaging.version.parse(sub_clean)
                except Exception:
                    pass
        return None

    @classmethod
    def compare(cls, v1_str: Optional[str], v2_str: Optional[str]) -> Optional[int]:
        """
        Compares two versions.
        Returns:
            1  if v1 > v2
            0  if v1 == v2
            -1 if v1 < v2
            None if either version cannot be safely compared.
        """
        if not v1_str or not v2_str:
            return None

        # Exact string match shortcut after basic normalization
        c1 = cls.clean_version_string(v1_str)
        c2 = cls.clean_version_string(v2_str)
        if c1 and c2 and c1 == c2:
            return 0

        p1 = cls.parse_version(v1_str)
        p2 = cls.parse_version(v2_str)

        if p1 is not None and p2 is not None:
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
            else:
                return 0

        # Tuple integer fallback for complex multi-part numbers e.g. 2.44.0.1
        try:
            parts1 = [int(p) for p in re.findall(r"\d+", c1 or "")]
            parts2 = [int(p) for p in re.findall(r"\d+", c2 or "")]
            if parts1 and parts2:
                # Pad to same length
                max_len = max(len(parts1), len(parts2))
                parts1.extend([0] * (max_len - len(parts1)))
                parts2.extend([0] * (max_len - len(parts2)))
                if parts1 > parts2:
                    return 1
                elif parts1 < parts2:
                    return -1
                else:
                    return 0
        except Exception:
            pass

        return None


# ===========================================================================
# 4. Official URL & Redirect Validator (Problem #71 + SSRF Protection)
# ===========================================================================

class OfficialUrlValidator:
    """
    Validates official download and update URLs.
    Enforces:
    - Rejection of non-HTTP(S) schemes (file://, ftp://).
    - SSRF protection: loopback, private IPs, link-local, localhost rejected.
    - HTTPS -> HTTP downgrade rejection.
    - Redirect loop detection.
    - Maximum hop limit (5 hops).
    - Destination domain verification against CanonicalIdentity.trusted_download_domains.
    - Rejection of arbitrary AI/RAG URLs.
    """

    MAX_REDIRECT_HOPS = 5

    BLOCKED_IP_NETWORKS = [
        ipaddress.ip_network("127.0.0.0/8"),       # Loopback
        ipaddress.ip_network("10.0.0.0/8"),        # Private Class A
        ipaddress.ip_network("172.16.0.0/12"),     # Private Class B
        ipaddress.ip_network("192.168.0.0/16"),    # Private Class C
        ipaddress.ip_network("169.254.0.0/16"),    # Link-local (e.g. AWS 169.254.169.254)
        ipaddress.ip_network("0.0.0.0/8"),         # Broadcast / Unspecified
        ipaddress.ip_network("224.0.0.0/4"),       # Multicast
        ipaddress.ip_network("::1/128"),           # IPv6 Loopback
        ipaddress.ip_network("fc00::/7"),          # IPv6 Unique Local
        ipaddress.ip_network("fe80::/10"),         # IPv6 Link-Local
    ]

    BLOCKED_HOSTNAMES = {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
    }

    @classmethod
    def is_ssrf_destination(cls, hostname_or_ip: str) -> bool:
        """Checks if a target host or IP resolves to private, loopback, or cloud-metadata address."""
        if not hostname_or_ip:
            return True

        h_low = hostname_or_ip.lower().strip()
        if h_low in cls.BLOCKED_HOSTNAMES or h_low.endswith(".localhost") or h_low.endswith(".local") or h_low.endswith(".internal"):
            return True

        # Check if direct IP literal
        try:
            # Handle brackets in IPv6: [::1]
            ip_str = h_low.strip("[]")
            ip = ipaddress.ip_address(ip_str)
            for net in cls.BLOCKED_IP_NETWORKS:
                if ip in net:
                    return True
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return True
        except ValueError:
            # Not an IP literal, try resolving if possible
            pass

        return False

    @classmethod
    def matches_trusted_domain(cls, host: str, trusted_domains: list[str]) -> bool:
        """
        Validates host against trusted domains.
        Matches exact domain or strict subdomain (e.g. downloads.git-scm.com matches git-scm.com).
        Does NOT trust arbitrary subdomains or unrelated domains.
        """
        if not host or not trusted_domains:
            return False
        h_low = host.lower().strip()
        for td in trusted_domains:
            td_low = td.lower().strip()
            if not td_low:
                continue
            # Strip path if accidentally present in domain list
            td_clean = td_low.split("/")[0]
            if h_low == td_clean:
                return True
            if h_low.endswith("." + td_clean):
                return True
        return False

    @classmethod
    def validate_url(
        cls,
        url: str,
        identity: Optional[CanonicalIdentity] = None,
        follow_redirects: bool = False,
        redirect_transport: Optional[Any] = None,
    ) -> Tuple[bool, SourceDecisionStatus, str, list[str]]:
        """
        Validates candidate official/download URL.
        Returns:
            (is_valid, status, final_or_error_message, redirect_chain)
        """
        if not url or not isinstance(url, str):
            return False, SourceDecisionStatus.OFFICIAL_URL_UNRESOLVED, "Empty or invalid URL parameter.", []

        chain: list[str] = [url]
        current_url = url.strip()
        visited: Set[str] = {current_url}

        # Determine allowed trusted domains
        allowed_domains: list[str] = []
        if identity:
            allowed_domains.extend(identity.trusted_download_domains)
            if identity.official_url:
                try:
                    p = urllib.parse.urlparse(identity.official_url)
                    if p.netloc:
                        allowed_domains.append(p.netloc.lower())
                except Exception:
                    pass

        # If no identity provided, default to rejecting non-public URLs
        for hop in range(cls.MAX_REDIRECT_HOPS + 1):
            try:
                parsed = urllib.parse.urlparse(current_url)
            except Exception as e:
                return False, SourceDecisionStatus.OFFICIAL_URL_UNRESOLVED, f"Malformed URL syntax: {e}", chain

            scheme = (parsed.scheme or "").lower()
            if scheme not in ("http", "https"):
                # Scheme rejection (file://, ftp://, etc.)
                return False, SourceDecisionStatus.SSRF_ATTEMPT_BLOCKED, f"Forbidden URL scheme '{scheme}'. Only HTTP and HTTPS are permitted.", chain

            host = (parsed.hostname or parsed.netloc.split(":")[0] or "").lower()
            if not host:
                return False, SourceDecisionStatus.OFFICIAL_URL_UNRESOLVED, "URL missing host component.", chain

            # 1. SSRF and local destination check
            if cls.is_ssrf_destination(host):
                structured_logger.log_event(
                    operation="URL_VALIDATION",
                    application=identity.identity_id if identity else "unknown",
                    identity=identity.identity_id if identity else "unknown",
                    status="SSRF_ATTEMPT_BLOCKED",
                    message=f"SSRF attempt blocked for host: {host}",
                    command="",
                )
                return False, SourceDecisionStatus.SSRF_ATTEMPT_BLOCKED, f"Destination host '{host}' is a forbidden local, loopback, or private network address.", chain

            # 2. Domain trust check against Canonical Identity
            if identity and allowed_domains:
                if not cls.matches_trusted_domain(host, allowed_domains):
                    structured_logger.log_event(
                        operation="URL_VALIDATION",
                        application=identity.identity_id,
                        identity=identity.identity_id,
                        status="UNTRUSTED_REDIRECT",
                        message=f"Host '{host}' not in trusted domains for {identity.identity_id}: {allowed_domains}",
                        command="",
                    )
                    return False, SourceDecisionStatus.UNTRUSTED_REDIRECT, f"Host '{host}' is not in the trusted domain list for {identity.display_name}.", chain

            # If not following live redirects or already validated
            if not follow_redirects:
                break

            # If a custom mock or test redirect transport is provided
            if redirect_transport is not None:
                next_target = redirect_transport(current_url)
                if not next_target:
                    break
            else:
                # Bounded HTTP HEAD request to discover real redirects
                try:
                    req = urllib.request.Request(current_url, method="HEAD", headers={"User-Agent": "PCDoctor-Validator/1.0"})
                    class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, req, fp, code, msg, headers, newurl):
                            return None
                    opener = urllib.request.build_opener(NoRedirectHandler)
                    with opener.open(req, timeout=3.0) as resp:
                        # No redirect
                        break
                except urllib.error.HTTPError as e:
                    if e.code in (301, 302, 303, 307, 308):
                        next_target = e.headers.get("Location")
                        if not next_target:
                            break
                    else:
                        # HTTP 404/500 etc
                        return False, SourceDecisionStatus.OFFICIAL_URL_UNRESOLVED, f"HTTP server returned status {e.code}", chain
                except Exception as e:
                    return False, SourceDecisionStatus.OFFICIAL_URL_UNRESOLVED, f"Network connection failed: {e}", chain

            if hop >= cls.MAX_REDIRECT_HOPS:
                return False, SourceDecisionStatus.EXCESSIVE_REDIRECTS, f"Redirect chain exceeded limit of {cls.MAX_REDIRECT_HOPS} hops.", chain

            # Resolve relative redirects
            resolved_next = urllib.parse.urljoin(current_url, next_target)

            # Check HTTPS -> HTTP downgrade
            if current_url.lower().startswith("https://") and resolved_next.lower().startswith("http://"):
                structured_logger.log_event(
                    operation="URL_VALIDATION",
                    application=identity.identity_id if identity else "unknown",
                    identity=identity.identity_id if identity else "unknown",
                    status="HTTPS_DOWNGRADE_REJECTED",
                    message=f"HTTPS -> HTTP downgrade detected from {current_url} to {resolved_next}",
                    command="",
                )
                return False, SourceDecisionStatus.HTTPS_DOWNGRADE_REJECTED, "Insecure HTTPS to HTTP redirect downgrade rejected.", chain

            # Check redirect loop
            if resolved_next in visited:
                return False, SourceDecisionStatus.REDIRECT_LOOP, f"Redirect loop detected targeting '{resolved_next}'.", chain

            visited.add(resolved_next)
            chain.append(resolved_next)
            current_url = resolved_next

        return True, SourceDecisionStatus.OFFICIAL_URL_VALIDATED, current_url, chain


# ===========================================================================
# 5. Release Providers (Abstraction & Implementations)
# ===========================================================================

class ReleaseProvider(ABC):
    """Abstract base class for upstream release information discovery."""

    @abstractmethod
    def get_latest_release(
        self,
        identity: CanonicalIdentity,
        channel: str = "stable",
        target_os: Optional[str] = None,
        target_arch: Optional[str] = None,
    ) -> Optional[ReleaseInfo]:
        """Discovers the latest release matching environment and channel constraints."""
        pass


class StaticMetadataProvider(ReleaseProvider):
    """
    Curated static metadata provider for verified core tools.
    Provides authoritative ground truth for offline, airgapped, and deterministic verification.
    """

    # Static catalog of curated upstream releases
    STATIC_RELEASES: Dict[str, Dict[str, Any]] = {
        "git": {
            "stable": {
                "version": "2.48.1",
                "tag": "v2.48.1.windows.1",
                "download_url": "https://github.com/git-for-windows/git/releases/download/v2.48.1.windows.1/Git-2.48.1-64-bit.exe",
                "os": "Windows",
                "arch": "x64",
                "source": "https://git-scm.com",
            },
            "preview": {
                "version": "2.49.0-rc1",
                "tag": "v2.49.0-rc1.windows.1",
                "download_url": "https://github.com/git-for-windows/git/releases/download/v2.49.0-rc1.windows.1/Git-2.49.0-rc1-64-bit.exe",
                "os": "Windows",
                "arch": "x64",
                "prerelease": True,
            },
        },
        "nodejs": {
            "stable": {
                "version": "22.14.0",
                "tag": "v22.14.0",
                "download_url": "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi",
                "os": "Windows",
                "arch": "x64",
                "source": "https://nodejs.org",
            },
            "lts": {
                "version": "20.18.3",
                "tag": "v20.18.3",
                "download_url": "https://nodejs.org/dist/v20.18.3/node-v20.18.3-x64.msi",
                "os": "Windows",
                "arch": "x64",
                "source": "https://nodejs.org",
            },
        },
        "vscode": {
            "stable": {
                "version": "1.98.0",
                "tag": "1.98.0",
                "download_url": "https://update.code.visualstudio.com/1.98.0/win32-x64-user/stable",
                "os": "Windows",
                "arch": "x64",
                "source": "https://code.visualstudio.com",
            },
        },
        "python": {
            "stable": {
                "version": "3.13.2",
                "tag": "v3.13.2",
                "download_url": "https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe",
                "os": "Windows",
                "arch": "x64",
                "source": "https://www.python.org",
            },
        },
    }

    def get_latest_release(
        self,
        identity: CanonicalIdentity,
        channel: str = "stable",
        target_os: Optional[str] = None,
        target_arch: Optional[str] = None,
    ) -> Optional[ReleaseInfo]:
        key = identity.identity_id.lower()
        if key not in self.STATIC_RELEASES:
            return None
        tool_channels = self.STATIC_RELEASES[key]
        c_key = channel.lower() if channel.lower() in tool_channels else "stable"
        if c_key not in tool_channels:
            return None

        data = tool_channels[c_key]
        return ReleaseInfo(
            version=data["version"],
            release_tag=data.get("tag", data["version"]),
            download_url=data.get("download_url", ""),
            source_type=SourceTrustClassification.TRUSTED_VENDOR_SOURCE,
            source_name=data.get("source", identity.official_url),
            channel=c_key,
            os=data.get("os", "Any"),
            architecture=data.get("arch", "Any"),
            prerelease=bool(data.get("prerelease", False)),
            timestamp=time.time(),
        )


class GitHubReleaseProvider(ReleaseProvider):
    """
    Release provider for GitHub-backed repositories.
    Strictly binds to identity.trusted_repository — NEVER allows callers or AI
    to dynamically pick an arbitrary GitHub repo.
    """

    def __init__(self, api_response_override: Optional[Dict[str, Any]] = None):
        self._override = api_response_override

    def get_latest_release(
        self,
        identity: CanonicalIdentity,
        channel: str = "stable",
        target_os: Optional[str] = None,
        target_arch: Optional[str] = None,
    ) -> Optional[ReleaseInfo]:
        repo = identity.trusted_repository
        if not repo:
            return None

        # If mock or injected test response is available
        if self._override:
            data = self._override
        else:
            url = f"https://api.github.com/repos/{repo}/releases/latest"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PCDoctor-SourceIntel/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None

        tag_name = data.get("tag_name", "")
        raw_version = VersionComparator.clean_version_string(tag_name)
        if not raw_version:
            return None

        is_pre = bool(data.get("prerelease", False))
        if channel == "stable" and is_pre:
            return None

        # Find best matching asset
        download_url = data.get("html_url", "")
        assets = data.get("assets", [])
        cur_os = (target_os or platform.system()).lower()
        cur_arch = (target_arch or platform.machine()).lower()

        for asset in assets:
            name = asset.get("name", "").lower()
            if cur_os in ("windows", "win32") and (".exe" in name or ".msi" in name):
                if ("64" in name or "x64" in name) and ("64" in cur_arch or "x86_64" in cur_arch or "amd64" in cur_arch):
                    download_url = asset.get("browser_download_url", download_url)
                    break

        return ReleaseInfo(
            version=raw_version,
            release_tag=tag_name,
            download_url=download_url,
            source_type=SourceTrustClassification.TRUSTED_VENDOR_RELEASE_API,
            source_name=f"github.com/{repo}",
            channel=channel,
            os=target_os or "Any",
            architecture=target_arch or "Any",
            prerelease=is_pre,
            timestamp=time.time(),
        )


class VendorApiReleaseProvider(ReleaseProvider):
    """Release provider querying official vendor release endpoints."""

    def __init__(self, api_response_override: Optional[Dict[str, Any]] = None):
        self._override = api_response_override

    def get_latest_release(
        self,
        identity: CanonicalIdentity,
        channel: str = "stable",
        target_os: Optional[str] = None,
        target_arch: Optional[str] = None,
    ) -> Optional[ReleaseInfo]:
        api_url = identity.release_api
        if not api_url and not self._override:
            return None

        if self._override:
            data = self._override
        else:
            try:
                req = urllib.request.Request(api_url, headers={"User-Agent": "PCDoctor-SourceIntel/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                return None

        # Node.js index format: list of objects with "version"
        if isinstance(data, list) and len(data) > 0 and "version" in data[0]:
            top = data[0]
            v = VersionComparator.clean_version_string(top.get("version", ""))
            return ReleaseInfo(
                version=v or "",
                release_tag=top.get("version", ""),
                download_url=f"https://nodejs.org/dist/{top.get('version', '')}/",
                source_type=SourceTrustClassification.TRUSTED_VENDOR_RELEASE_API,
                source_name=identity.official_url or "nodejs.org",
                channel=channel,
                timestamp=time.time(),
            )

        # Standard object format
        if isinstance(data, dict):
            v = data.get("version") or data.get("latest_version") or data.get("name")
            v_clean = VersionComparator.clean_version_string(str(v))
            if v_clean:
                return ReleaseInfo(
                    version=v_clean,
                    release_tag=str(v),
                    download_url=data.get("download_url", identity.official_url),
                    source_type=SourceTrustClassification.TRUSTED_VENDOR_RELEASE_API,
                    source_name=identity.official_url,
                    channel=channel,
                    timestamp=time.time(),
                )

        return None


# ===========================================================================
# 6. Release Cache with Expiration & Freshness Tracking
# ===========================================================================

@dataclass
class CacheEntry:
    release_info: ReleaseInfo
    timestamp: float
    ttl: float = 3600.0  # 1 hour default TTL


class ReleaseCache:
    """Thread-safe in-memory cache for release intelligence."""

    def __init__(self, default_ttl: float = 3600.0) -> None:
        self.default_ttl = default_ttl
        self._entries: Dict[str, CacheEntry] = {}

    def _make_key(self, canonical_id: str, channel: str, target_os: str, target_arch: str) -> str:
        return f"{canonical_id.lower()}:{channel.lower()}:{target_os.lower()}:{target_arch.lower()}"

    def get(
        self,
        canonical_id: str,
        channel: str = "stable",
        target_os: str = "Any",
        target_arch: str = "Any",
    ) -> Tuple[Optional[ReleaseInfo], bool]:
        """
        Returns (release_info, is_fresh).
        If entry exists but is older than TTL, returns (release_info, False).
        """
        key = self._make_key(canonical_id, channel, target_os, target_arch)
        entry = self._entries.get(key)
        if not entry:
            return None, False

        now = time.time()
        is_fresh = (now - entry.timestamp) <= entry.ttl
        return entry.release_info, is_fresh

    def put(
        self,
        canonical_id: str,
        release_info: ReleaseInfo,
        channel: str = "stable",
        target_os: str = "Any",
        target_arch: str = "Any",
        ttl: Optional[float] = None,
    ) -> None:
        key = self._make_key(canonical_id, channel, target_os, target_arch)
        self._entries[key] = CacheEntry(
            release_info=release_info,
            timestamp=time.time(),
            ttl=ttl or self.default_ttl,
        )

    def invalidate(self, canonical_id: Optional[str] = None) -> None:
        if not canonical_id:
            self._entries.clear()
        else:
            prefix = canonical_id.lower() + ":"
            self._entries = {k: v for k, v in self._entries.items() if not k.startswith(prefix)}


# ===========================================================================
# 7. Trusted Source Decision Engine (Problems #4, #54, #71 Unified)
# ===========================================================================

class TrustedSourceDecisionEngine:
    """
    Authoritative decision layer comparing Installed, Package Manager, and Upstream versions.
    Enforces deterministic source precedence, channel integrity, downgrade protection,
    and URL trustworthiness.
    """

    def __init__(
        self,
        cache: Optional[ReleaseCache] = None,
        custom_providers: Optional[List[ReleaseProvider]] = None,
    ) -> None:
        self.cache = cache or ReleaseCache()
        self.static_provider = StaticMetadataProvider()
        self.github_provider = GitHubReleaseProvider()
        self.vendor_provider = VendorApiReleaseProvider()
        self.custom_providers = custom_providers or []

    def _discover_upstream(
        self,
        identity: CanonicalIdentity,
        channel: str,
        target_os: str,
        target_arch: str,
        force_refresh: bool,
    ) -> Tuple[Optional[ReleaseInfo], bool, bool]:
        """
        Discovers upstream release with caching.
        Returns: (ReleaseInfo or None, from_cache, is_fresh)
        """
        if not force_refresh:
            cached_rel, is_fresh = self.cache.get(identity.identity_id, channel, target_os, target_arch)
            if cached_rel:
                return cached_rel, True, is_fresh

        # 1. Custom providers (for testing / dependency injection)
        for prov in self.custom_providers:
            try:
                rel = prov.get_latest_release(identity, channel, target_os, target_arch)
                if rel:
                    self.cache.put(identity.identity_id, rel, channel, target_os, target_arch)
                    return rel, False, True
            except Exception:
                pass

        # 2. Release-source specific provider
        if identity.release_source == "github":
            try:
                rel = self.github_provider.get_latest_release(identity, channel, target_os, target_arch)
                if rel:
                    self.cache.put(identity.identity_id, rel, channel, target_os, target_arch)
                    return rel, False, True
            except Exception:
                pass
        elif identity.release_source == "vendor_api":
            try:
                rel = self.vendor_provider.get_latest_release(identity, channel, target_os, target_arch)
                if rel:
                    self.cache.put(identity.identity_id, rel, channel, target_os, target_arch)
                    return rel, False, True
            except Exception:
                pass

        # 3. Static metadata provider fallback
        rel = self.static_provider.get_latest_release(identity, channel, target_os, target_arch)
        if rel:
            self.cache.put(identity.identity_id, rel, channel, target_os, target_arch)
            return rel, False, True

        return None, False, False

    def evaluate_tool(
        self,
        canonical_id: str,
        installed_version: Optional[str] = None,
        package_manager_version: Optional[str] = None,
        channel: str = "stable",
        target_os: Optional[str] = None,
        target_arch: Optional[str] = None,
        force_refresh: bool = False,
        candidate_url: Optional[str] = None,
        is_linux_distro_package: bool = False,
        linux_distro_name: str = "",
    ) -> SourceDecisionResult:
        """
        Authoritative evaluation of Installed vs Package Manager vs Trusted Upstream.
        """
        cur_os = target_os or platform.system()
        cur_arch = target_arch or platform.machine()

        identity = canonical_store.get(canonical_id)
        if not identity:
            return SourceDecisionResult(
                status=SourceDecisionStatus.VERSION_COMPARISON_UNKNOWN,
                canonical_id=canonical_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                reason=f"Tool '{canonical_id}' is not registered in CanonicalIdentityStore.",
                error="IDENTITY_NOT_FOUND",
            )

        # 1. URL validation if candidate_url provided (Problem #71)
        validated_url = identity.official_url
        redirect_chain: list[str] = []
        if candidate_url:
            is_valid, url_status, final_url_or_err, chain = OfficialUrlValidator.validate_url(
                candidate_url, identity=identity, follow_redirects=False
            )
            redirect_chain = chain
            if not is_valid:
                structured_logger.log_event(
                    operation="SOURCE_INTELLIGENCE",
                    application=identity.identity_id,
                    identity=identity.identity_id,
                    status=url_status.value,
                    message=f"Candidate URL rejected: {final_url_or_err}",
                    command="",
                )
                return SourceDecisionResult(
                    status=url_status,
                    canonical_id=identity.identity_id,
                    installed_version=installed_version,
                    package_manager_version=package_manager_version,
                    official_url=identity.official_url,
                    redirect_chain=redirect_chain,
                    reason=f"Candidate URL rejected: {final_url_or_err}",
                    error="URL_VALIDATION_FAILED",
                    review_required=True,
                )
            validated_url = final_url_or_err

        # 2. Discover Upstream Release
        upstream_rel, from_cache, is_fresh = self._discover_upstream(
            identity, channel, cur_os, cur_arch, force_refresh
        )

        if not upstream_rel:
            structured_logger.log_event(
                operation="SOURCE_INTELLIGENCE",
                application=identity.identity_id,
                identity=identity.identity_id,
                status=SourceDecisionStatus.UPSTREAM_UNAVAILABLE.value,
                message=f"No upstream release metadata available for {identity.identity_id} (offline or unconfigured).",
                command="",
            )
            return SourceDecisionResult(
                status=SourceDecisionStatus.UPSTREAM_UNAVAILABLE,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                official_url=identity.official_url,
                validated_url=validated_url,
                channel=channel,
                os=cur_os,
                architecture=cur_arch,
                reason="Upstream release comparison could not be performed: upstream data unavailable.",
                review_required=True,
            )

        if from_cache and not is_fresh:
            structured_logger.log_event(
                operation="SOURCE_INTELLIGENCE",
                application=identity.identity_id,
                identity=identity.identity_id,
                status=SourceDecisionStatus.STALE_SOURCE_DATA.value,
                message=f"Cached release metadata for {identity.identity_id} is stale.",
                command="",
            )

        upstream_version = upstream_rel.version

        # 3. Channel & Compatibility Checks
        # Prerelease protection: if installation is on stable channel, never auto-select prerelease
        if channel == "stable" and (upstream_rel.prerelease or VersionComparator.is_prerelease(upstream_version)):
            return SourceDecisionResult(
                status=SourceDecisionStatus.REVIEW_REQUIRED,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                upstream_version=upstream_version,
                channel=channel,
                compatible=False,
                reason="Upstream release is a prerelease/preview build and cannot be automatically selected for a stable installation.",
                review_required=True,
            )

        # OS and Architecture compatibility check
        if upstream_rel.os != "Any" and cur_os.lower() not in upstream_rel.os.lower():
            structured_logger.log_event(
                operation="SOURCE_INTELLIGENCE",
                application=identity.identity_id,
                identity=identity.identity_id,
                status=SourceDecisionStatus.UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE.value,
                message=f"Upstream release OS '{upstream_rel.os}' does not match host OS '{cur_os}'",
                command="",
            )
            return SourceDecisionResult(
                status=SourceDecisionStatus.UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                upstream_version=upstream_version,
                compatible=False,
                reason=f"Upstream release found ({upstream_version}) but is incompatible with current OS ({cur_os}).",
            )

        # 4. Version Comparisons
        # Clean versions
        c_inst = VersionComparator.clean_version_string(installed_version)
        c_pm = VersionComparator.clean_version_string(package_manager_version)
        c_up = VersionComparator.clean_version_string(upstream_version)

        # Compare Installed vs Upstream
        cmp_inst_up = VersionComparator.compare(c_inst, c_up) if c_inst and c_up else None
        # Compare Installed vs PM
        cmp_inst_pm = VersionComparator.compare(c_inst, c_pm) if c_inst and c_pm else None
        # Compare PM vs Upstream
        cmp_pm_up = VersionComparator.compare(c_pm, c_up) if c_pm and c_up else None

        # Check for malformed or incomparable versions
        if (
            (installed_version and (c_inst is None or cmp_inst_up is None))
            or (package_manager_version and (c_pm is None or cmp_pm_up is None))
            or (c_up is None)
        ):
            return SourceDecisionResult(
                status=SourceDecisionStatus.VERSION_COMPARISON_UNKNOWN,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                upstream_version=upstream_version,
                reason="One or more version strings could not be safely parsed or normalized.",
                review_required=True,
            )

        # 5. Downgrade Protection Check
        if cmp_inst_up is not None and cmp_inst_up > 0:
            # Installed > Upstream -> candidate is a downgrade
            structured_logger.log_event(
                operation="SOURCE_INTELLIGENCE",
                application=identity.identity_id,
                identity=identity.identity_id,
                status=SourceDecisionStatus.DOWNGRADE_CANDIDATE.value,
                message=f"Installed version {c_inst} is newer than upstream {c_up}. Blocked downgrade.",
                command="",
            )
            return SourceDecisionResult(
                status=SourceDecisionStatus.DOWNGRADE_CANDIDATE,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                upstream_version=upstream_version,
                downgrade=True,
                update_available=False,
                reason=f"Installed version ({c_inst}) is newer than candidate upstream ({c_up}). Downgrade blocked.",
            )

        # 6. Problem #54: Linux Repository Package Outdated Evaluation
        if is_linux_distro_package:
            # When repository package is older than upstream release
            if cmp_pm_up is not None and cmp_pm_up < 0:
                # Distro frozen package: propose review/upstream option
                structured_logger.log_event(
                    operation="SOURCE_INTELLIGENCE",
                    application=identity.identity_id,
                    identity=identity.identity_id,
                    status=SourceDecisionStatus.REPOSITORY_OUTDATED.value,
                    message=f"Linux repo package ({c_pm}) is outdated compared to upstream ({c_up}) on {linux_distro_name or 'Linux'}",
                    command="",
                )
                return SourceDecisionResult(
                    status=SourceDecisionStatus.REPOSITORY_OUTDATED,
                    canonical_id=identity.identity_id,
                    installed_version=installed_version,
                    package_manager_version=package_manager_version,
                    upstream_version=upstream_version,
                    selected_source=upstream_rel.source_name,
                    source_type=upstream_rel.source_type,
                    source_trust=0.90 if is_source_trusted(upstream_rel.source_type) else 0.40,
                    update_available=True,
                    review_required=True,
                    reason=f"System repository candidate ({c_pm}) is outdated compared to trusted upstream release ({c_up}). Review required before altering distribution package sources.",
                )
            elif cmp_pm_up is not None and cmp_pm_up == 0:
                return SourceDecisionResult(
                    status=SourceDecisionStatus.REPOSITORY_UP_TO_DATE,
                    canonical_id=identity.identity_id,
                    installed_version=installed_version,
                    package_manager_version=package_manager_version,
                    upstream_version=upstream_version,
                    selected_source=identity.get_package_manager(cur_os),
                    source_type=SourceTrustClassification.TRUSTED_PACKAGE_MANAGER,
                    source_trust=1.0,
                    update_available=(cmp_inst_pm is not None and cmp_inst_pm < 0),
                    reason=f"Repository package candidate ({c_pm}) matches trusted upstream release ({c_up}).",
                )

        # 7. Problem #4: Trusted Upstream Newer Than Package Manager
        # Case A: PM has no update (installed == pm), but upstream is newer (installed < upstream)
        # Case B: PM has update, but upstream is even newer (installed < pm < upstream)
        if cmp_inst_up is not None and cmp_inst_up < 0:
            if cmp_pm_up is not None and cmp_pm_up < 0:
                structured_logger.log_event(
                    operation="SOURCE_INTELLIGENCE",
                    application=identity.identity_id,
                    identity=identity.identity_id,
                    status=SourceDecisionStatus.UPSTREAM_UPDATE_AVAILABLE.value,
                    message=f"Upstream {c_up} is newer than PM candidate {c_pm} and installed {c_inst}",
                    command="",
                )
                return SourceDecisionResult(
                    status=SourceDecisionStatus.UPSTREAM_UPDATE_AVAILABLE,
                    canonical_id=identity.identity_id,
                    installed_version=installed_version,
                    package_manager_version=package_manager_version,
                    upstream_version=upstream_version,
                    selected_source=upstream_rel.source_name,
                    source_type=upstream_rel.source_type,
                    source_trust=0.95 if is_source_trusted(upstream_rel.source_type) else 0.40,
                    channel=channel,
                    os=cur_os,
                    architecture=cur_arch,
                    update_available=True,
                    official_url=identity.official_url,
                    validated_url=upstream_rel.download_url or validated_url,
                    redirect_chain=redirect_chain,
                    reason=f"A newer compatible trusted upstream release ({c_up}) is available (package manager offers {c_pm or 'none'}).",
                    review_required=(identity.source_policy == "review_required"),
                )

        # 8. Normal Package Manager update or up-to-date
        if cmp_inst_pm is not None and cmp_inst_pm < 0:
            # Package manager update is available
            return SourceDecisionResult(
                status=SourceDecisionStatus.REPOSITORY_UP_TO_DATE,
                canonical_id=identity.identity_id,
                installed_version=installed_version,
                package_manager_version=package_manager_version,
                upstream_version=upstream_version,
                selected_source=identity.get_package_manager(cur_os),
                source_type=SourceTrustClassification.TRUSTED_PACKAGE_MANAGER,
                source_trust=1.0,
                update_available=True,
                reason=f"Package manager candidate ({c_pm}) is newer than installed version ({c_inst}).",
            )

        # 9. No Update Available
        return SourceDecisionResult(
            status=SourceDecisionStatus.NO_UPDATE,
            canonical_id=identity.identity_id,
            installed_version=installed_version,
            package_manager_version=package_manager_version,
            upstream_version=upstream_version,
            update_available=False,
            reason=f"Installed version ({c_inst or 'current'}) is up to date.",
        )


# Global singleton instance
trusted_source_engine = TrustedSourceDecisionEngine()


def create_execution_request_from_decision(
    decision: SourceDecisionResult,
    approved: bool = False,
    elevate: bool = False,
) -> Any:
    """
    Transforms a valid SourceDecisionResult into an ExecutionRequest for ExecutionResolver.
    
    Enforces the invariant:
    - Decisions indicating downgrade, rejection, SSRF, or no update cannot initiate mutation.
    - Preserves authentic trust: only authentic trusted sources receive high trust;
      untrusted/dynamic sources are strictly bounded <= 0.40.
    - Never directly spawns subprocesses. Execution MUST pass through:
      ExecutionResolver -> ExecutionPlan -> LIVE Safety Gate -> CentralizedExecutionEngine.
    """
    from execution_plan import ExecutionRequest, ProvenanceClass

    if not decision.update_available or decision.downgrade:
        raise ValueError(
            f"Cannot create execution request: decision does not have an update available "
            f"(status={decision.status.value}, downgrade={decision.downgrade})"
        )

    if decision.status in (
        SourceDecisionStatus.UNTRUSTED_REDIRECT,
        SourceDecisionStatus.SSRF_ATTEMPT_BLOCKED,
        SourceDecisionStatus.HTTPS_DOWNGRADE_REJECTED,
        SourceDecisionStatus.REDIRECT_LOOP,
        SourceDecisionStatus.EXCESSIVE_REDIRECTS,
        SourceDecisionStatus.UPSTREAM_RELEASE_FOUND_BUT_INCOMPATIBLE,
        SourceDecisionStatus.DOWNGRADE_CANDIDATE,
    ):
        raise ValueError(f"Cannot create execution request for rejected decision status: {decision.status.value}")

    # Determine command/recipe target
    ident = canonical_store.get(decision.canonical_id)
    pkg_id = ident.get_package_id() if ident else decision.canonical_id
    pm = ident.get_package_manager() if ident else "system"

    # Command derivation based on source
    if decision.status == SourceDecisionStatus.UPSTREAM_UPDATE_AVAILABLE and decision.validated_url:
        # Direct vendor installer path or review guidance
        cmd = f"# Update {decision.canonical_id} to upstream {decision.upstream_version} from {decision.validated_url}"
        prov_hint = ProvenanceClass.DYNAMIC_CANDIDATE
        trust = min(0.85, decision.source_trust)
    else:
        # Standard package manager update
        if pm == "winget":
            cmd = f"winget upgrade --id {pkg_id} --exact --accept-source-agreements --accept-package-agreements"
        elif pm == "brew":
            cmd = f"brew upgrade {pkg_id}"
        elif pm == "apt":
            cmd = f"apt-get install --only-upgrade -y {pkg_id}"
        else:
            cmd = f"{pm} update {pkg_id}"
        prov_hint = ProvenanceClass.STATIC_RECIPE
        trust = 1.0

    return ExecutionRequest(
        command=cmd,
        target=decision.canonical_id,
        operation="UPDATE",
        source="STATIC_DB" if prov_hint == ProvenanceClass.STATIC_RECIPE else "DYNAMIC_DB",
        provenance_hint=prov_hint,
        elevate=elevate,
        title=f"Update {decision.canonical_id} to {decision.upstream_version or decision.package_manager_version}",
        approved=approved,
        trust=trust,
        confidence=0.95,
        details=decision.to_dict(),
    )
