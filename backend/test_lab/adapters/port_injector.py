"""
test_lab/adapters/port_injector.py — Generic controlled port conflict injector.

Uses dedicated non-critical test ports to verify port conflict detection and resolution.
"""

from __future__ import annotations

import socket
import threading
from typing import Dict, Optional
from test_lab.adapters.base import FaultInjector
from test_lab.models import BaselineRecord, FaultDefinition
from dev_environment_detector import dev_environment_detector


class PortConflictFaultInjector(FaultInjector):
    """Generic controlled port conflict fault injector."""

    def __init__(self) -> None:
        self._sockets: Dict[int, socket.socket] = {}
        self._lock = threading.Lock()

    def inject(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        port = fault_def.metadata.get("port", 18765)
        try:
            with self._lock:
                if port in self._sockets:
                    return True
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                s.listen(1)
                self._sockets[port] = s
            return self.verify_fault_present(fault_def, baseline)
        except Exception:
            return False

    def verify_fault_present(self, fault_def: FaultDefinition, baseline: BaselineRecord) -> bool:
        port = fault_def.metadata.get("port", 18765)
        return dev_environment_detector.check_port(port)

    def restore(self, baseline: BaselineRecord) -> bool:
        port = baseline.original_state.get("port", 18765)
        with self._lock:
            s = self._sockets.pop(port, None)
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        return True

    def verify_restored(self, baseline: BaselineRecord) -> bool:
        port = baseline.original_state.get("port", 18765)
        return not dev_environment_detector.check_port(port)
