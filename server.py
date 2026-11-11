# SPDX-License-Identifier: AGPL-3.0-only
import email
import email.policy
import imaplib
import json
import os
from pathlib import Path
import re
import ssl
from typing import Annotated
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from native_http import clean, request, secret

mcp=FastMCP("mailu")
def api(path,body=None):
    raw=request("MAILU_API_URL",path,None if body is None else json.dumps(body).encode(),
                {"Authorization":secret("MAILU_API_TOKEN_FILE"),"Content-Type":"application/json"})
    if not raw.strip():
        return {}
    try:
        value=json.loads(raw)
    except ValueError:
        raise ValueError("Unexpected response from Mailu.") from None
    if isinstance(value,dict) and value.get("error"):
        raise ValueError("Mailu rejected the operation.")
    return clean(value)

def address(value):
    if not re.fullmatch(r"[^@\s/\x00-\x1f]+@[^@\s/\x00-\x1f]+",value) or len(value)>254:
        raise ValueError("Invalid mailbox address.")
    return value.lower()

@mcp.tool()
def mailu_status():
    """List domains visible through this Mailu API token."""
    return {"domains":api("/domain")}

@mcp.tool()
def mailu_list_mailboxes():
    """List mailbox metadata visible to the configured administrator."""
    return api("/user")

@mcp.tool()
def mailu_get_mailbox(email:str):
    """Read one mailbox's administrative metadata."""
    return api("/user/"+quote(address(email),safe=""))

@mcp.tool()
def mailu_list_aliases():
    """List aliases for the configured Mailu installation."""
    return api("/alias")

@mcp.tool()
def mailu_create_alias(email:str,destination:list[str],comment:str=""):
    """Create an alias for existing local mailboxes and read it back."""
    alias=address(email); dest=[address(x) for x in destination]
    if not dest or not set(dest)<={x["email"].lower() for x in mailu_list_mailboxes()}:
        raise ValueError("Destinations must be existing local mailboxes.")
    if alias in {x["email"].lower() for x in mailu_list_aliases()}:
        raise ValueError("Alias already exists.")
    api("/alias",{"email":alias,"destination":dest,"comment":comment,"wildcard":False})
    result=api("/alias/"+quote(alias,safe=""))
    return {"verified":result.get("email","").lower()==alias and set(result.get("destination",[]))==set(dest),"alias":result}

@mcp.tool()
def mailu_create_mailbox(email:str,quota_bytes:Annotated[int,Field(ge=0)]=1073741824,comment:str=""):
    """Create an ordinary mailbox with its operator-provisioned initial password and read back metadata."""
    name=address(email)
    if name in {x["email"].lower() for x in mailu_list_mailboxes()}:
        raise ValueError("Mailbox already exists.")
    keydir=os.getenv("MAILU_NEW_PASSWORD_DIR")
    if not keydir:
        raise ValueError("Configure MAILU_NEW_PASSWORD_DIR for mailbox creation.")
    import hashlib
    keyfile=Path(keydir).expanduser()/(hashlib.sha256(name.encode()).hexdigest()+".txt")
    if keyfile.is_symlink() or not keyfile.is_file():
        raise ValueError("Provision an initial password file for this address as described in README.")
    password=keyfile.read_text(encoding="utf-8-sig").rstrip("\r\n")
    if not password:
        raise ValueError("The initial password file is empty.")
    api("/user",{"email":name,"raw_password":password,"quota_bytes":quota_bytes,"comment":comment,
                 "global_admin":False,"enabled":True,"enable_imap":True,"enable_pop":False,"allow_spoofing":False})
    row=mailu_get_mailbox(name)
    return {"verified":row.get("email","").lower()==name,"mailbox":row}

def mailbox(mail):
    user=address(os.environ.get("MAILU_IMAP_USER",""))
    if address(mail)!=user:
        raise ValueError("Select the account profile for this IMAP mailbox.")
    host=os.environ.get("MAILU_IMAP_HOST")
    if not host:
        raise ValueError("Set MAILU_IMAP_HOST and MAILU_IMAP_PASSWORD_FILE.")
    conn=imaplib.IMAP4_SSL(host,int(os.getenv("MAILU_IMAP_PORT","993")),ssl_context=ssl.create_default_context(),timeout=30)
    try:
        conn.login(user,secret("MAILU_IMAP_PASSWORD_FILE"))
        if conn.select("INBOX",readonly=True)[0]!="OK":
            raise ValueError("Cannot open INBOX.")
        validity=conn.response("UIDVALIDITY")[1][0].decode("ascii")
        return conn,validity
    except Exception:
        conn.logout()
        raise ValueError("Cannot access the configured IMAP mailbox.") from None

def fetch(conn,uid,spec):
    typ,rows=conn.uid("fetch",uid,spec)
    if typ!="OK":
        raise ValueError("IMAP fetch failed.")
    return next((row[1] for row in rows if isinstance(row,tuple) and isinstance(row[1],bytes)),b"")

def headers(raw):
    m=email.message_from_bytes(raw,policy=email.policy.default)
    return {k:str(m.get(k,"")) for k in ("From","To","Subject","Date","Message-ID")}

@mcp.tool()
def mailu_list_messages(email:str,limit:Annotated[int,Field(ge=1,le=50)]=10,offset:Annotated[int,Field(ge=0)]=0):
    """Read recent INBOX headers via IMAP and return UIDVALIDITY-qualified message IDs."""
    conn,validity=mailbox(email)
    try:
        typ,rows=conn.uid("search",None,"ALL")
        if typ!="OK":
            raise ValueError("IMAP search failed.")
        uids=rows[0].split()[::-1][offset:offset+limit]
        return [{"id":validity+"-"+uid.decode(),"headers":headers(fetch(conn,uid,"(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)]<0.65536>)"))} for uid in uids]
    finally:
        conn.logout()

@mcp.tool()
def mailu_read_message(email:str,id:str):
    """Read one bounded message without marking it as seen."""
    if not re.fullmatch(r"\d+-\d+",id):
        raise ValueError("Use a message ID from mailu_list_messages.")
    conn,validity=mailbox(email)
    try:
        epoch,uid=id.split("-")
        if epoch!=validity:
            raise ValueError("INBOX identity changed. Refresh the message list.")
        raw=fetch(conn,uid,"(BODY.PEEK[]<0.2097153>)")
        if not raw or len(raw)>2097152:
            raise ValueError("Message unavailable or exceeds 2 MiB.")
        msg=email.message_from_bytes(raw,policy=email.policy.default)
        part=msg.get_body(preferencelist=("plain","html"))
        return {"headers":headers(raw),"body":str(part.get_content())[:16000] if part else "",
                "untrusted_content":True}
    finally:
        conn.logout()

if __name__=="__main__":
    mcp.run(transport="stdio")
