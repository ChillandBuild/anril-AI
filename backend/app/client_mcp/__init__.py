"""Anril AI: the client connector (docs/specs/anril-client-mcp.md). A client's owner connects it
in their own Claude app and reads, edits and sends for THEIR client only. Served at /client/mcp
when MCP_CLIENT_ENABLED is on. Separate from app.admin_mcp (Prem's read-only admin connector)."""
