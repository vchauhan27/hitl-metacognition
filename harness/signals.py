"""Shared signal type emitted by every failure module and consumed by the Controller."""


class MonitorSignal:
    def __init__(self, gap_type: str, severity: str, message: str, requires_ask: bool = False,
                 failure_type: str = "", options: list | None = None):
        self.gap_type = gap_type
        self.severity = severity  # 'low', 'medium', 'high'
        self.message = message
        self.requires_ask = requires_ask
        # Which human failure type this signal is a fix for (monitoring / control / ...)
        self.failure_type = failure_type
        # Optional concrete choices to offer the user when the Controller routes to "ask"
        self.options = options or []

    def __repr__(self):
        return (f"MonitorSignal({self.failure_type}:{self.gap_type}, {self.severity}, "
                f"requires_ask={self.requires_ask})")
