"""Private profile approval and remote read-only MCP endpoints."""
import asyncio
from contextlib import AsyncExitStack,asynccontextmanager
from html import escape
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlencode,urlsplit

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route

from native_store import Records
from workstation_oauth import WorkstationOAuth, SCOPE
from workstation_profiles import profiles

ACTION={
 "netease-music":("netease_user_library",{"action":"collected_playlists","limit":10},"读取这个网易云音乐账号收藏的歌单。"),
 "yxtown-study":("yxtown_my_courses",{"view":"learning","pages":1},"读取这个账号正在学习的课程。"),
 "komari":("komari_list_servers",{},"读取这个监控账号可见的服务器。"),
 "hestiacp":("hestia_list_websites",{},"读取这个面板用户的网站。"),
 "mailu":("mailu_list_messages",{},"读取这个邮箱账号最近十封邮件。"),
}
PROFILE={"type":"object","properties":{"id":{"type":"string","minLength":1},"name":{"type":"string"}},"required":["id"],"additionalProperties":False}
READ={"readOnlyHint":True,"destructiveHint":False}


def build_one(root,slug,origin,private,db):
    product=json.loads((root/"connector.json").read_text(encoding="utf8"))
    name=product["id"]
    auth=WorkstationOAuth(origin,private,Records(db,name))
    m=FastMCP(product["title"],auth=auth,mask_error_details=True)
    def identity():
        token=get_access_token()
        row=profiles(name).get(token.claims["alias"],{}) if token else {}
        if not token or row.get("id")!=token.subject or row.get("fingerprint")!=token.claims.get("fingerprint"):
            raise ValueError("Reconnect the selected profile.")
        return row
    @m.tool(name="connected_profile",output_schema=PROFILE,annotations=READ,meta={"openai/profile":True})
    def profile()->dict[str,str]:
        """Identify the workstation account selected at authorization."""
        row=identity()
        return {"id":row["id"],"name":row["name"]}
    def register(tool,args,description):
        @m.tool(name=tool,description=description,annotations=READ)
        async def read():
            row=identity()
            spec={"root":str(root),"product":name,"alias":row["alias"],"fingerprint":row["fingerprint"],"action":{"tool":tool,"args":args}}
            env={**os.environ,"PYTHONIOENCODING":"utf-8"}
            proc=await asyncio.create_subprocess_exec(sys.executable,"-X","utf8",str(Path(__file__).with_name("workstation_profiles.py")),
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env)
            try:
                raw,_=await asyncio.wait_for(proc.communicate(json.dumps(spec).encode()),110)
            finally:
                if proc.returncode is None:proc.kill();await proc.wait()
            if proc.returncode or len(raw)>4000000:raise ValueError("Local provider unavailable.")
            result=json.loads(raw)
            if result.get("isError"):raise ValueError("Local provider unavailable.")
            return result.get("structuredContent",result.get("content"))
    register(*ACTION[name])
    if name=="mailu":
        register("mailu_status",{},"读取此 Mailu 账号的服务状态。")
    return product,auth,m


def build(settings):
    private="http://127.0.0.1:"+str(settings["approval_port"])
    scope_names={}
    routes=[]
    apps=[]
    state_dir=Path(settings["state_dir"]);state_dir.mkdir(parents=True,exist_ok=True)
    base=settings["origin"].rstrip("/")
    if urlsplit(base).scheme!="https" or urlsplit(base).path:raise ValueError("Expected an HTTPS origin.")
    for slug,folder in settings["products"].items():
        if not slug.replace("-","").isalnum():raise ValueError("Invalid route.")
        root=Path(folder)
        path="/codex-accounts/"+slug
        product,auth,m=build_one(root,slug,base+path,private,state_dir/"grants.sqlite")
        scope_names[product["id"]]=(product,auth,root)
        child=m.http_app(path="/mcp",stateless_http=True,json_response=True);apps.append(child)
        for route in auth.get_well_known_routes("/mcp"):
            if not route.path.endswith((path,path+"/mcp")):continue
            if "oauth-authorization-server" in route.path:
                previous=route.app
                async def send_metadata(scope,receive,send,original=previous):
                    initial=None
                    async def rewrite(event):
                        nonlocal initial
                        if event["type"]=="http.response.start":
                            initial=event;return
                        if event["type"]=="http.response.body" and initial and initial["status"]==200:
                            data=json.loads(event["body"]);data["authorization_response_iss_parameter_supported"]=True
                            event={**event,"body":json.dumps(data).encode()}
                            from starlette.datastructures import MutableHeaders
                            MutableHeaders(scope=initial)["content-length"]=str(len(event["body"]))
                        if initial:await send(initial);initial=None
                        await send(event)
                    await original(scope,receive,rewrite)
                route.app=send_metadata
                routes.append(route)
            else:routes.append(route)
        routes.append(Mount(path,app=child))
    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            for child in apps:await stack.enter_async_context(child.router.lifespan_context(child))
            yield
    public=Starlette(routes=routes,lifespan=lifespan)
    def fail():return PlainTextResponse("此授权已失效。请从插件的「管理」重新连接。",status_code=400)
    async def choose(request:Request):
        if request.headers.get("host")!=urlsplit(private).netloc:return fail()
        params=request.query_params if request.method=="GET" else await request.form()
        app=params.get("app","");ticket=params.get("request","")
        if app not in scope_names or len(ticket)>200:return fail()
        product,auth,root=scope_names[app];session=auth.store.read("request",ticket)
        cookie_name="ldai_approval_"+auth.store.key(ticket)[:16]
        if not session:return fail()
        headers={"Cache-Control":"no-store","Referrer-Policy":"same-origin","X-Frame-Options":"DENY","Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://chatgpt.com http://127.0.0.1:*; frame-ancestors 'none'; base-uri 'none'"}
        if request.method=="POST":
            cookie=request.cookies.get(cookie_name,"")
            if request.headers.get("origin")!=private:return PlainTextResponse("授权窗口来源验证失败，请从插件重新连接。",status_code=400)
            if not cookie or not secrets.compare_digest(cookie,params.get("csrf","")):return PlainTextResponse("授权窗口凭据已失效，请重新连接。",status_code=400)
            proof=auth.store.read("approval",cookie,consume=True)
            if proof!={"ticket":ticket}:return fail()
            if params.get("op")=="setup":
                # The account manager is local UI, with provider-specific login and private credential storage.
                executable=Path(sys.executable)
                if os.name=="nt" and executable.with_name("pythonw.exe").exists():executable=executable.with_name("pythonw.exe")
                import subprocess
                subprocess.Popen([str(executable),str(root/"account_manager.py")],cwd=root,
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return RedirectResponse(private+"/choose?"+urlencode({"app":app,"request":ticket}),status_code=303,headers={"Cache-Control":"no-store"})
            row=profiles(app).get(params.get("profile",""))
            if not row:return fail()
            redirect=auth.approve(ticket,row)
            response=RedirectResponse(redirect,status_code=303,headers={"Cache-Control":"no-store","Referrer-Policy":"no-referrer"})
            response.delete_cookie(cookie_name,path="/choose")
            return response
        csrf=auth.store.issue("approval",{"ticket":ticket},600)
        opts="".join('<option value="'+escape(a,quote=True)+'">'+escape(r["name"])+'</option>' for a,r in profiles(app).items())
        hidden="".join('<input type="hidden" name="'+k+'" value="'+escape(v,quote=True)+'">' for k,v in {"app":app,"request":ticket,"csrf":csrf}.items())
        title=escape(product["title"])
        body=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} · 连接账号</title><style>body{{font:17px system-ui;color:#252527;background:#f6f6f5;padding:7vh 20px}}main{{margin:auto;max-width:520px;padding:32px;background:white;border-radius:14px}}label,select{{display:block;margin:16px 0}}button,select{{font:inherit;padding:8px 12px}}button{{margin:3px}}</style><main><h1>连接{title}</h1><p>选择允许 Codex 读取的本机账号。凭据保存在此工作站。</p><form method="post" action="/choose">{hidden}<label>账号<select name="profile">{opts}</select></label><button name="op" value="approve" {'disabled' if not opts else ''}>允许连接</button><button name="op" value="setup">添加或登录账号</button></form></main></html>"""
        response=HTMLResponse(body,headers=headers)
        response.set_cookie(cookie_name,csrf,max_age=600,httponly=True,samesite="strict",path="/choose")
        return response
    return public, Starlette(routes=[Route("/choose",choose,methods=["GET","POST"])])
