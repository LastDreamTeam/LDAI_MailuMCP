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


import smtplib
from email.message import EmailMessage
from email.utils import getaddresses,make_msgid

def provisioned_password(name):
    import hashlib
    folder=os.getenv("MAILU_NEW_PASSWORD_DIR")
    if not folder:raise ValueError("Set MAILU_NEW_PASSWORD_DIR for the selected account.")
    root=Path(folder).expanduser().resolve(strict=True)
    p=root/(hashlib.sha256(address(name).encode()).hexdigest()+".txt")
    if p.is_symlink() or p.resolve().parent!=root or not p.is_file():raise ValueError("Provision this mailbox's password file first.")
    value=p.read_text(encoding="utf-8-sig").rstrip("\r\n")
    if not value:raise ValueError("Empty password file.")
    return value

@mcp.tool()
def mailu_change_password(email:str):
    """Set a mailbox password using the same private file convention as mailbox creation."""
    name=address(email)
    if mailu_get_mailbox(name).get("email","").lower()!=name:raise ValueError("Mailbox not found.")
    request("MAILU_API_URL","/user/"+quote(name,safe=""),json.dumps({"raw_password":provisioned_password(name)}).encode(),
            {"Authorization":secret("MAILU_API_TOKEN_FILE"),"Content-Type":"application/json"},method="PATCH")
    return {"provider_accepted":True,"mailbox":name}

def submit(to,cc,subject,body,reply_id=None,refs=None):
    sender=address(os.environ.get("MAILU_SMTP_USER") or os.environ.get("MAILU_IMAP_USER",""))
    if not to or len(to)+len(cc)>100 or not body or len(body)>500000 or any(c in subject for c in "\r\n"):
        raise ValueError("Provide recipients, a one-line subject and a message body.")
    msg=EmailMessage();msg["From"]=sender;msg["To"]=", ".join(address(x) for x in to)
    if cc:msg["Cc"]=", ".join(address(x) for x in cc)
    msg["Subject"]=subject;msg["Message-ID"]=make_msgid(domain=sender.split("@")[-1])
    if reply_id:msg["In-Reply-To"]=reply_id;msg["References"]=refs or reply_id
    msg.set_content(body)
    host=os.getenv("MAILU_SMTP_HOST")
    if not host:raise ValueError("Set MAILU_SMTP_HOST and mailbox credentials in the account manager.")
    mode=os.getenv("MAILU_SMTP_MODE","starttls")
    if mode not in ("starttls","tls"):raise ValueError("Select starttls or tls.")
    port=int(os.getenv("MAILU_SMTP_PORT") or ("465" if mode=="tls" else "587"))
    context=ssl.create_default_context()
    password=secret("MAILU_SMTP_PASSWORD_FILE" if os.getenv("MAILU_SMTP_PASSWORD_FILE") else "MAILU_IMAP_PASSWORD_FILE")
    with (smtplib.SMTP_SSL(host,port,context=context,timeout=30) if mode=="tls" else smtplib.SMTP(host,port,timeout=30)) as smtp:
        if mode=="starttls":smtp.starttls(context=context)
        smtp.login(sender,password)
        refused=smtp.send_message(msg)
    return {"message_id":str(msg["Message-ID"]),"accepted_by_smtp":not refused,"refused_recipients":list(refused)}

@mcp.tool()
def mailu_send_email(to:list[str],subject:str,body:str,cc:list[str]|None=None):
    """Send a message from the selected mailbox, with optional carbon-copy recipients."""
    return submit(to,cc or [],subject,body)

@mcp.tool()
def mailu_reply(email:str,id:str,body:str,cc:list[str]|None=None):
    """Reply to a selected INBOX message with optional explicit carbon copies."""
    if not re.fullmatch(r"\d+-\d+",id):raise ValueError("Select a message returned by mailu_list_messages.")
    conn,epoch=mailbox(email)
    try:
        validity,uid=id.split("-")
        if epoch!=validity:raise ValueError("Mailbox changed. Refresh the message list.")
        data=fetch(conn,uid,"(BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO SUBJECT MESSAGE-ID REFERENCES)]<0.65536>)")
        if not data:raise ValueError("Message header unavailable.")
        from email.parser import BytesParser
        src=BytesParser(policy=__import__("email").policy.default).parsebytes(data)
    finally:conn.logout()
    recipients=[addr for _,addr in getaddresses([str(src.get("Reply-To") or src.get("From") or "")])]
    subj=str(src.get("Subject",""));mid=str(src.get("Message-ID","")).strip()
    ids=re.findall(r"<[^<>\s]+>",str(src.get("References",""))+" "+mid)[-20:]
    return submit(recipients,cc or [],subj if subj.lower().startswith("re:") else "Re: "+subj,body,
                  mid if re.fullmatch(r"<[^<>\s]+>",mid) else None," ".join(ids))

if __name__=="__main__":
    mcp.run(transport="stdio")
