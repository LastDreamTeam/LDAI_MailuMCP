"""Read only the selected local profile. This module never returns its configuration to a client."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ALIAS = re.compile(r"[a-z][a-z0-9_-]{0,15}\Z")


def profiles(product, location=None):
    path=location or Path.home()/".config"/"ldai-mcp"/product/"accounts.json"
    if not path.is_file():
        return {}
    data=json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("connector")!=product:
        raise ValueError("Wrong connector profile file.")
    result={}
    for alias,entry in data["accounts"].items():
        if not ALIAS.fullmatch(alias):continue
        binding={k:v for k,v in entry.items() if k!="label"}
        fingerprint=hashlib.sha256(json.dumps(binding,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        stable=hashlib.sha256((product+"\x00"+alias+"\x00"+fingerprint).encode()).hexdigest()
        result[alias]={"alias":alias,"fingerprint":fingerprint,"id":stable,"name":entry.get("label") or alias}
    return result


def handle_read(root, product, alias, fingerprint, action):
    """Called in a fresh child process with one statically configured operation."""
    if profiles(product).get(alias,{}).get("fingerprint")!=fingerprint:raise ValueError("Reconnect this profile.")
    sys.path.insert(0,str(root))
    import asyncio
    import router
    if router.NAME!=product:raise ValueError("Wrong local package.")
    for k in router.PRODUCT["providerEnvironment"]:os.environ.pop(k,None)
    entry=router.profiles().get(alias)
    if not entry or entry.get("_invalid"):raise ValueError("The local profile needs configuration.")
    if product=="hestiacp" and action["tool"]=="hestia_list_websites":
        user=entry.get("env",{}).get("HESTIA_USER")
        if not user:raise ValueError("Define HESTIA_USER for this profile.")
        args={"user":user}
    elif product=="mailu" and action["tool"]=="mailu_list_messages":
        user=entry.get("env",{}).get("MAILU_IMAP_USER")
        if not user:raise ValueError("This profile has no bound mailbox.")
        args={"email":user,"limit":10}
    else:args=action.get("args",{})
    async def run():
        worker=router.Worker(alias,entry)
        try:
            result=await worker.request("tools/call",{"name":action["tool"],"arguments":args})
            if result.get("isError"):raise RuntimeError("The provider declined the read.")
            return result
        finally:
            if worker.proc and worker.proc.stdin:
                worker.proc.stdin.close()
                try:await asyncio.wait_for(worker.proc.wait(),2)
                except asyncio.TimeoutError:pass
            await worker.close()
    return asyncio.run(run())


if __name__=="__main__":
    try:
        options=json.load(sys.stdin)
        result=handle_read(Path(options["root"]),options["product"],options["alias"],options["fingerprint"],options["action"])
        print(json.dumps(result,ensure_ascii=False))
    except Exception:
        print('{"isError":true,"content":[{"type":"text","text":"The selected local account could not perform this read."}]}')
        sys.exit(1)
