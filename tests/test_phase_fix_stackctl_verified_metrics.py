from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_API_DIR = REPO_ROOT / "paper_api"
for path in (str(PAPER_API_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import stackctl


class PhaseFixStackctlVerifiedMetricsTests(unittest.TestCase):
    def test_burnin_gate_ignores_stopped_optional_services_when_policies_are_disabled(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 4,
                "drift_count": 0,
                "launch_context": {},
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "private_stream_loop", "alive": False, "drift_detected": False, "drift_pids": []},
                    {"service_name": "auto_execute_loop", "alive": False, "drift_detected": False, "drift_pids": []},
                    {"service_name": "trade_management_loop", "alive": False, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": None,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-22T13:46:15+00:00",
                        "last_summary": {
                            "overall": {
                                "health": "error",
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-22T13:26:28+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "private_stream:stream-main",
                    "summary": "private stream stream-main is stale",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertNotIn("private_stream_daemon_stopped", codes)
        self.assertNotIn("auto_execution_daemon_stopped", codes)
        self.assertNotIn("trade_management_daemon_stopped", codes)
        self.assertNotIn("operations_health_error", codes)
        self.assertIn("operations_health_optional_component_error", codes)
        self.assertIn("recent_optional_component_errors_ignored", codes)

    def test_burnin_gate_ignores_optional_private_stream_errors_without_subject_key(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 4,
                "drift_count": 0,
                "launch_context": {},
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": None,
            },
            "runtimes": {
                "private_stream": [
                    {"updated_at": "2026-04-22T14:02:31+00:00", "connection_status": "streaming", "last_error": {}},
                ],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-22T14:02:31+00:00",
                        "last_summary": {"overall": {"health": "error"}},
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-22T12:54:29+00:00",
                    "event_type": "stream_error",
                    "owner_key": "stream-main",
                    "severity": "error",
                    "source": "private_stream",
                    "subject_key": None,
                    "summary": "private stream error: [Errno 60] Operation timed out",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertNotIn("operations_health_error", codes)
        self.assertNotIn("recent_error_events", codes)
        self.assertIn("operations_health_optional_component_error", codes)
        self.assertIn("recent_optional_component_errors_ignored", codes)

    def test_burnin_gate_still_blocks_when_private_stream_is_planned_and_stopped(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 2,
                "drift_count": 0,
                "launch_context": {
                    "planned_services": ["server", "scan_loop", "private_stream_loop"],
                },
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "private_stream_loop", "alive": False, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": None,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [],
                "auto_execution": [],
                "trade_management": [],
                "concept_lab": [],
            },
            "recent_events": [],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "blocked")
        self.assertIn("private_stream_daemon_stopped", codes)
        self.assertEqual(codes["private_stream_daemon_stopped"]["severity"], "error")

    def test_burnin_gate_flags_service_pid_drift(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/tmp/trading-paper-stack",
            "db_path": "/tmp/trading-paper-trading.db",
            "manifest": {
                "alive_count": 1,
                "drift_count": 1,
                "items": [
                    {
                        "service_name": "scan_loop",
                        "alive": True,
                        "drift_detected": True,
                        "drift_pids": [1111],
                    }
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": None,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [],
                "auto_execution": [],
                "trade_management": [],
                "concept_lab": [],
            },
            "recent_events": [],
            "recent_scan_history": [
                {
                    "scan_id": "scan-1",
                }
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("service_pid_drift_detected", codes)
        self.assertEqual(codes["service_pid_drift_detected"]["severity"], "warning")

    def test_burnin_gate_uses_main_operations_runtime_instead_of_newest_public_market_row(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/tmp/trading-paper-stack",
            "db_path": "/tmp/trading-paper-trading.db",
            "manifest": {
                "alive_count": 1,
                "drift_count": 0,
                "items": [
                    {
                        "service_name": "ops_loop",
                        "alive": True,
                        "drift_detected": False,
                        "drift_pids": [],
                    }
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": None,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "public_market:default",
                        "updated_at": "2026-04-21T12:10:00+00:00",
                        "last_summary": {
                            "event_path_state": "degraded_fallback",
                        },
                    },
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-21T12:09:00+00:00",
                        "last_summary": {
                            "overall": {
                                "health": "warning",
                            }
                        },
                    },
                ],
                "auto_execution": [],
                "trade_management": [],
                "concept_lab": [],
            },
            "recent_events": [],
            "recent_scan_history": [
                {
                    "scan_id": "scan-1",
                }
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertIn("operations_health_warning", codes)
        self.assertNotIn("operations_health_ok", codes)

    def test_burnin_gate_downgrades_optional_private_stream_staleness_and_old_errors(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 4,
                "drift_count": 0,
                "launch_context": {},
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "supervisor_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "ops_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {
                    "private_stream_loop": {"has_snapshot": True, "matches": True, "changed_keys": []},
                },
                "service_launch": {
                    "private_stream_loop": {"started_at": "2026-04-22T12:00:00+00:00"},
                },
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": "2026-04-22T13:56:59+00:00",
            },
            "runtimes": {
                "private_stream": [
                    {
                        "updated_at": "2026-04-22T14:02:31+00:00",
                        "connection_status": "streaming",
                        "last_error": {},
                    },
                ],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-22T14:09:01+00:00",
                        "last_summary": {"overall": {"health": "error"}},
                        "state": {
                            "component_state": {
                                "private_stream:stream-main": {
                                    "component_key": "private_stream:stream-main",
                                    "health": "error",
                                    "status": "stale",
                                    "summary": "private stream stream-main is stale",
                                },
                                "supervisor:main": {
                                    "component_key": "supervisor:main",
                                    "health": "healthy",
                                    "status": "healthy",
                                    "summary": "supervisor runtime main is healthy",
                                },
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-22T12:53:11+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "supervisor:main",
                    "summary": "supervisor runtime main is stale",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("private_stream_optional_component_unhealthy", codes)
        self.assertIn("operations_health_optional_component_error", codes)
        self.assertIn("recent_error_events_recovered", codes)
        self.assertNotIn("operations_health_error", codes)
        self.assertNotIn("recent_error_events", codes)

    def test_burnin_gate_treats_missing_optional_private_stream_as_recovered_for_public_errors(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 4,
                "drift_count": 0,
                "launch_context": {
                    "planned_services": ["server", "scan_loop", "supervisor_loop", "ops_loop"],
                },
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "supervisor_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "ops_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": "2026-04-22T13:56:59+00:00",
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-22T14:09:01+00:00",
                        "last_summary": {"overall": {"health": "warning"}},
                        "state": {
                            "component_state": {
                                "private_stream": {
                                    "component_key": "private_stream",
                                    "health": "warning",
                                    "status": "missing",
                                    "summary": "no private stream runtime has been recorded yet",
                                },
                                "public_market_event_path": {
                                    "component_key": "public_market_event_path",
                                    "health": "healthy",
                                    "status": "healthy_primary",
                                    "summary": "public candle-close event path is healthy",
                                },
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-22T14:02:31+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "public_market_event_path",
                    "summary": "public candle-close event path is not healthy enough",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("private_stream_runtime_missing", codes)
        self.assertIn("operations_health_optional_component_warning", codes)
        self.assertIn("recent_error_events_recovered", codes)
        self.assertNotIn("operations_health_warning", codes)
        self.assertNotIn("recent_error_events", codes)

    def test_burnin_gate_downgrades_startup_warmup_error_after_operations_moves_past_it(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 5,
                "drift_count": 0,
                "launch_context": {
                    "planned_services": ["server", "scan_loop", "supervisor_loop", "ops_loop", "concept_lab_loop"],
                },
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "supervisor_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "ops_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "concept_lab_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": "2026-04-27T12:23:07+00:00",
                "grace_window_seconds": 90,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-27T12:33:10+00:00",
                        "last_summary": {"overall": {"health": "warning"}},
                        "state": {
                            "component_state": {
                                "private_stream": {
                                    "component_key": "private_stream",
                                    "health": "warning",
                                    "status": "missing",
                                    "summary": "no private stream runtime has been recorded yet",
                                },
                                "public_market_event_path": {
                                    "component_key": "public_market_event_path",
                                    "health": "warning",
                                    "status": "degraded_fallback",
                                    "summary": "fallback polling is currently carrying scans",
                                },
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [
                    {
                        "updated_at": "2026-04-27T12:33:13+00:00",
                        "state": {"last_error": None},
                    },
                ],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-27T12:23:08+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "public_market_event_path",
                    "summary": "public candle-close event path is not healthy enough and fallback polling is not carrying scans",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("recent_error_events_startup_recovered", codes)
        self.assertIn("operations_health_warning", codes)
        self.assertNotIn("recent_error_events", codes)

    def test_burnin_gate_downgrades_prestart_error_after_current_launch_is_observed(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 5,
                "drift_count": 0,
                "launch_context": {
                    "planned_services": ["server", "scan_loop", "supervisor_loop", "ops_loop", "concept_lab_loop"],
                },
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "supervisor_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "ops_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "concept_lab_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": "2026-04-27T12:35:51+00:00",
                "grace_window_seconds": 90,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-27T12:37:35+00:00",
                        "last_summary": {"overall": {"health": "warning"}},
                        "state": {
                            "component_state": {
                                "private_stream": {
                                    "component_key": "private_stream",
                                    "health": "warning",
                                    "status": "missing",
                                    "summary": "no private stream runtime has been recorded yet",
                                },
                                "public_market_event_path": {
                                    "component_key": "public_market_event_path",
                                    "health": "warning",
                                    "status": "degraded_fallback",
                                    "summary": "fallback polling is currently carrying scans",
                                },
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [
                    {
                        "updated_at": "2026-04-27T12:37:35+00:00",
                        "state": {"last_error": None},
                    },
                ],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-27T12:23:08+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "public_market_event_path",
                    "summary": "public candle-close event path is not healthy enough and fallback polling is not carrying scans",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("recent_error_events_prestart", codes)
        self.assertIn("operations_health_warning", codes)
        self.assertNotIn("recent_error_events", codes)

    def test_burnin_gate_treats_degraded_fallback_public_market_as_recovered_after_error(self):
        burnin_report_payload = {
            "ok": True,
            "state_dir": "/Users/tester/Library/Application Support/trading/stack",
            "db_path": "/Users/tester/Library/Application Support/trading/paper-trading.db",
            "manifest": {
                "alive_count": 5,
                "drift_count": 0,
                "launch_context": {
                    "planned_services": ["server", "scan_loop", "supervisor_loop", "ops_loop", "concept_lab_loop"],
                },
                "items": [
                    {"service_name": "server", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "scan_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "supervisor_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "ops_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                    {"service_name": "concept_lab_loop", "alive": True, "drift_detected": False, "drift_pids": []},
                ],
            },
            "controls": [],
            "env": {
                "comparisons": {},
                "service_launch": {},
            },
            "startup": {
                "grace_active": False,
                "launch_started_at": "2026-04-27T12:41:02+00:00",
                "grace_window_seconds": 90,
            },
            "runtimes": {
                "private_stream": [],
                "operations": [
                    {
                        "runtime_key": "main",
                        "updated_at": "2026-04-27T15:46:56+00:00",
                        "last_summary": {"overall": {"health": "warning"}},
                        "state": {
                            "component_state": {
                                "private_stream": {
                                    "component_key": "private_stream",
                                    "health": "warning",
                                    "status": "missing",
                                    "summary": "no private stream runtime has been recorded yet",
                                },
                                "public_market_event_path": {
                                    "component_key": "public_market_event_path",
                                    "health": "warning",
                                    "status": "degraded_fallback",
                                    "summary": "public candle-close event path is degraded and fallback polling is currently carrying scans",
                                },
                            }
                        },
                    }
                ],
                "auto_execution": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "trade_management": [
                    {"last_summary": {"policy_enabled": False}},
                ],
                "concept_lab": [
                    {
                        "updated_at": "2026-04-27T15:47:10+00:00",
                        "state": {"last_error": None},
                    },
                ],
            },
            "recent_events": [
                {
                    "created_at": "2026-04-27T15:41:25+00:00",
                    "event_type": "component_alert",
                    "severity": "error",
                    "source": "operations",
                    "subject_key": "public_market_event_path",
                    "summary": "public candle-close event path is not healthy enough and fallback polling is not carrying scans",
                }
            ],
            "recent_scan_history": [
                {"scan_id": "scan-1"},
            ],
        }

        with patch.object(stackctl, "burnin_report", return_value=burnin_report_payload):
            result = stackctl.burnin_gate(type("Args", (), {})())

        codes = {item["code"]: item for item in result["issues"]}
        self.assertEqual(result["overall"], "watch")
        self.assertIn("operations_health_warning", codes)
        self.assertIn("recent_error_events_recovered", codes)
        self.assertNotIn("recent_error_events", codes)

    def test_verified_only_baseline_counts_only_verified_paper_trade(self):
        mapping = {
            "verified_paper_trade": 2,
            "paper_trade": 7,
            "no_paper_trade": 11,
        }

        self.assertEqual(stackctl.count_candidate_decisions(mapping), 2)
        self.assertEqual(stackctl.count_candidate_decisions(mapping, include_legacy=True), 9)

    def test_legacy_paper_trade_does_not_inflate_default_candidate_totals(self):
        summary = stackctl.summarize_candidate_scan_metrics(
            [
                {"decision": "verified_paper_trade", "candidate_logged": True},
                {"decision": "paper_trade", "candidate_logged": True},
                {"decision": "paper_trade", "candidate_logged": False},
                {"decision": "no_paper_trade", "candidate_logged": False},
            ]
        )

        self.assertEqual(summary["verified_candidate_count"], 1)
        self.assertEqual(summary["legacy_candidate_count"], 2)
        self.assertEqual(len(summary["logged_verified_candidates"]), 1)

    def test_sample_scan_summaries_reflect_verified_only_baseline_cleanly(self):
        replay_item = {
            "verified_trade_count": 3,
            "legacy_compat_trade_count": 8,
            "verified_trade_ratio": 0.15,
            "legacy_compat_trade_ratio": 0.4,
        }

        self.assertEqual(stackctl.replay_metric_count(replay_item), 3)
        self.assertEqual(stackctl.replay_metric_count(replay_item, include_legacy=True), 11)

    def test_replay_metric_count_does_not_silently_fallback_to_legacy_alias(self):
        replay_item = {
            "verified_trade_count": 3,
            "paper_trade_count": 8,
        }

        self.assertEqual(stackctl.replay_metric_count(replay_item), 3)
        self.assertEqual(stackctl.replay_metric_count(replay_item, include_legacy=True), 3)

    def test_compatibility_reporting_is_clearly_separated(self):
        mapping = {
            "verified_paper_trade": 1,
            "paper_trade": 4,
        }

        self.assertEqual(stackctl.count_verified_candidate_decisions(mapping), 1)
        self.assertEqual(stackctl.count_legacy_candidate_decisions(mapping), 4)

    def test_stackctl_strips_legacy_compat_metrics_from_default_json_payloads(self):
        payload = {
            "summaries": [
                {
                    "instrument": "BTCUSDT",
                    "verified_trade_count": 2,
                    "legacy_compat_trade_count": 7,
                    "decision_counts": {
                        "verified_paper_trade": 2,
                        "paper_trade": 7,
                    },
                }
            ],
            "legacy_compat_trade_ratio": 0.35,
        }

        stripped = stackctl.strip_legacy_compat_metrics(payload)

        self.assertNotIn("legacy_compat_trade_ratio", stripped)
        self.assertNotIn("legacy_compat_trade_count", stripped["summaries"][0])
        self.assertNotIn("paper_trade", stripped["summaries"][0]["decision_counts"])
        self.assertEqual(stripped["summaries"][0]["verified_trade_count"], 2)

    def test_wave4_text_summary_hides_legacy_compat_ratio_unless_requested(self):
        result = {
            "overall": "ready",
            "state_dir": "/tmp/stack",
            "counts": {},
            "issues": [],
            "replay_tuning": {
                "summaries": [
                    {
                        "instrument": "BTCUSDT",
                        "verified_trade_ratio": 0.2,
                        "legacy_compat_trade_ratio": 0.7,
                        "top_blockers": [],
                    }
                ]
            },
        }

        output = io.StringIO()
        with redirect_stdout(output):
            stackctl.print_wave4_review_text(result)
        self.assertNotIn("legacy_compat_ratio", output.getvalue())

        result["legacy_compat_metrics_included"] = True
        output = io.StringIO()
        with redirect_stdout(output):
            stackctl.print_wave4_review_text(result)
        self.assertIn("legacy_compat_ratio=70%", output.getvalue())

    def test_concept_review_default_scan_metrics_exclude_legacy_compat_rows(self):
        fixture = {
            "overall": "ready",
            "state_dir": "/tmp/stack",
            "db_path": "/tmp/trading.db",
            "burnin_gate": {
                "overall": "ready",
                "issues": [],
                "report": {
                    "manifest": {
                        "items": [
                            {
                                "service_name": "scan_loop",
                                "alive": True,
                                "started_at": "2026-04-20T00:00:00+00:00",
                            }
                        ]
                    },
                    "runtimes": {},
                    "recent_concept_events": [],
                    "recent_scan_history": [
                        {
                            "decision": "verified_paper_trade",
                            "candidate_logged": True,
                            "created_at": "2026-04-20T00:05:00+00:00",
                        },
                        {
                            "decision": "paper_trade",
                            "candidate_logged": True,
                            "created_at": "2026-04-20T00:06:00+00:00",
                        },
                    ],
                    "recent_proposals": [],
                    "recent_execution_actions": [],
                    "recent_execution_state": [],
                    "recent_auto_execution_events": [],
                },
            },
            "replay_tuning": {"summaries": []},
            "issues": [],
            "next_focus": [],
        }

        args = type(
            "Args",
            (),
            {
                "include_legacy_compat_metrics": False,
                "policy_path": str(stackctl.CONCEPT_DECISION_POLICY_PATH),
            },
        )()
        with patch.object(stackctl, "wave4_review", return_value=fixture):
            result = stackctl.concept_review(args)

        self.assertFalse(result["legacy_compat_metrics_included"])
        self.assertEqual(result["scan_metrics"]["verified_candidate_scan_count"], 1)
        self.assertNotIn("legacy_candidate_scan_count", result["scan_metrics"])
        self.assertNotIn("paper_trade", result["scan_mix"])
        self.assertNotIn(
            "concept_legacy_candidate_compatibility_present",
            {item["code"] for item in result["issues"]},
        )

    def test_concept_review_can_opt_into_separated_legacy_compat_rows(self):
        fixture = {
            "overall": "ready",
            "state_dir": "/tmp/stack",
            "db_path": "/tmp/trading.db",
            "burnin_gate": {
                "overall": "ready",
                "issues": [],
                "report": {
                    "manifest": {
                        "items": [
                            {
                                "service_name": "scan_loop",
                                "alive": True,
                                "started_at": "2026-04-20T00:00:00+00:00",
                            }
                        ]
                    },
                    "runtimes": {},
                    "recent_concept_events": [],
                    "recent_scan_history": [
                        {
                            "decision": "verified_paper_trade",
                            "candidate_logged": True,
                            "created_at": "2026-04-20T00:05:00+00:00",
                        },
                        {
                            "decision": "paper_trade",
                            "candidate_logged": True,
                            "created_at": "2026-04-20T00:06:00+00:00",
                        },
                    ],
                    "recent_proposals": [],
                    "recent_execution_actions": [],
                    "recent_execution_state": [],
                    "recent_auto_execution_events": [],
                },
            },
            "replay_tuning": {"summaries": []},
            "issues": [],
            "next_focus": [],
        }

        args = type(
            "Args",
            (),
            {
                "include_legacy_compat_metrics": True,
                "policy_path": str(stackctl.CONCEPT_DECISION_POLICY_PATH),
            },
        )()
        with patch.object(stackctl, "wave4_review", return_value=fixture):
            result = stackctl.concept_review(args)

        self.assertTrue(result["legacy_compat_metrics_included"])
        self.assertEqual(result["scan_metrics"]["verified_candidate_scan_count"], 1)
        self.assertEqual(result["scan_metrics"]["legacy_candidate_scan_count"], 1)
        self.assertEqual(result["scan_mix"]["paper_trade"], 1)
        self.assertIn(
            "concept_legacy_candidate_compatibility_present",
            {item["code"] for item in result["issues"]},
        )


if __name__ == "__main__":
    unittest.main()
