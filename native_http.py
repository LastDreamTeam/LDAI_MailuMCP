# SPDX-License-Identifier: AGPL-3.0-only
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):
        return None

def secret(var):
    try:
        value=Path(os.environ[var]).expanduser().read_text(encoding="utf-8-sig").strip()
    except (KeyError,OSError):
        raise ValueError("Configure a readable "+var+".") from None
    if not value:
        raise ValueError("Empty credential file.")
    return value

def request(var, path, body=None, headers=None, method=None):
    base=os.environ.get(var,"").rstrip("/")
    u=urlsplit(base)
    if not u.hostname or u.username or u.password or u.fragment or u.query or not (
        u.scheme=="https" or u.scheme=="http" and u.hostname in ("localhost","127.0.0.1","::1")
    ):
        raise ValueError("Set "+var+" to the service HTTPS base URL or an HTTP loopback URL.")
    req=Request(base+path,data=body,headers=headers or {},method=method)
    try:
        with build_opener(NoRedirect()).open(req,timeout=30) as response:
            raw=response.read(4*1024*1024+1)
    except HTTPError as e:
        raise ValueError(f"Provider returned HTTP {e.code}.") from None
    except (URLError,OSError):
        raise ValueError("Provider connection failed. Verify the URL and TLS trust.") from None
    if len(raw)>4*1024*1024:
        raise ValueError("Response too large.")
    return raw

def clean(value):
    if isinstance(value,list):
        return [clean(x) for x in value]
    if isinstance(value,dict):
        return {k:clean(v) for k,v in value.items() if not re.search(
            r"passw|passwd|token|secret|private.?key|api.?key|^hash$|^u_hash$|^two.?factor|otp|dkim_private",k,re.I)}
    return value
