"""
CwDaemon — Compound Wiki Universal Daemon v2
=============================================

A standalone daemon that provides universal AI memory for ANY Agent.
All Agents just send conversation data via HTTP; daemon handles everything else.

Usage:
    cw daemon start --wiki ./wiki --port 9877
    cw daemon stop
    cw daemon status

Agent integration (any language):
    POST http://localhost:9877/hook  {"user_message": "...", "ai_response": "..."}
"""

__version__ = "2.0.0"
