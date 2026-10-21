"""Create private production settings on the VPS without displaying secrets."""
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess


root = Path(__file__).resolve().parents[1]
destination = root / ".env.production"
if destination.exists():
    raise SystemExit(".env.production already exists. Edit it manually; nothing was overwritten.")

network = "docsproject_proxy"
result = subprocess.run(
    ["docker", "network", "inspect", network], capture_output=True, text=True,
)
if result.returncode:
    raise SystemExit("Create the docsproject_proxy Docker network first, then run this script again.")

subnets = json.loads(result.stdout)[0]["IPAM"]["Config"]
ipv4 = next((item["Subnet"] for item in subnets if ":" not in item.get("Subnet", "")), None)
if not ipv4:
    raise SystemExit("The Caddy network needs an IPv4 subnet.")
ipaddress.ip_network(ipv4)

replacements = {
    "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
    "ADMIN_API_KEY": secrets.token_urlsafe(32),
    "TRUSTED_PROXY_IPS": ipv4,
}
lines = []
for line in (root / "deploy" / "production.env.example").read_text().splitlines():
    name = line.split("=", 1)[0]
    lines.append(f"{name}={replacements[name]}" if name in replacements else line)

descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w") as output:
    output.write("\n".join(lines) + "\n")
print("Created .env.production with private database/admin keys and proxy settings.")
print("Edit VOYAGE_API_KEY and GROQ_API_KEY before starting the application.")
