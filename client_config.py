# SPDX-License-Identifier: AGPL-3.0-only
"""Print an MCP client entry for this checkout. Run from any working directory."""
import argparse
import json
import os
from pathlib import Path
import sys

NAME = "mailu"
ALLOWED = ['LDAI_ACCOUNTS_FILE', 'LDAI_MCP_PYTHON', 'MAILU_API_URL', 'MAILU_API_TOKEN_FILE', 'MAILU_IMAP_HOST', 'MAILU_IMAP_USER', 'MAILU_IMAP_PORT', 'MAILU_IMAP_PASSWORD_FILE', 'MAILU_NEW_PASSWORD_DIR']
ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client", choices=["cursor","dsh","codex"])
    parser.add_argument("--env", action="append", default=[], metavar="SETTING=VALUE",
                        help="Set a non-secret path or option in the generated configuration")
    args = parser.parse_args()
    env = {}
    for assignment in args.env:
        key, separator, value = assignment.partition("=")
        if key not in ALLOWED or not separator or not value:
            parser.error("Allowed path/settings keys: " + ", ".join(sorted(ALLOWED)))
        env[key] = value
    venv = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    command = str(venv) if venv.is_file() else sys.executable
    argv = [str(ROOT / "router.py")]
    entry = {"command":command,"args":argv}
    if env:
        entry["env"] = env
    if args.client == "cursor":
        print(json.dumps({"mcpServers":{NAME:entry}}, ensure_ascii=False, indent=2))
    elif args.client == "dsh":
        print("- id: mcp-" + NAME)
        print("  name: '@deepseek-ai/dsh-mcp-client'")
        print("  config:")
        print("    serverName: " + NAME + "\n    transport: stdio")
        for key, value in entry.items():
            print("    " + key + ": " + json.dumps(value,ensure_ascii=False))
        print("    toolCallTimeoutMs: 250000")
    else:
        print("[mcp_servers." + NAME + "]")
        for key in ("command","args"):
            print(key + " = " + json.dumps(entry[key],ensure_ascii=False))
        print("tool_timeout_sec = 250")
        if env:
            print("[mcp_servers." + NAME + ".env]")
            for key, value in env.items():
                print(key + " = " + json.dumps(value,ensure_ascii=False))

if __name__ == "__main__":
    main()
