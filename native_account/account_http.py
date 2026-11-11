# SPDX-License-Identifier: AGPL-3.0-only
"""Authenticated read-only pilot for this connector. No default or caller-selected local account."""
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StdioTransport
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token

ROOT=Path(__file__).resolve().parents[1]
PRODUCT=json.loads((ROOT/'connector.json').read_text(encoding='utf8'))['id']
SCOPE='connector.read'
SCHEMA={'type':'object','properties':{'id':{'type':'string','minLength':1},'name':{'type':'string'}},'required':['id'],'additionalProperties':False}
# Each checkout supplies ONE matching entry. Unknown products must not inherit another service.
SERVICE=json.loads((Path(__file__).parent/'service.json').read_text(encoding='utf8'))
if SERVICE['product']!=PRODUCT:raise RuntimeError('Service definition does not match this checkout.')

def https(value):
    x=urlsplit(value)
    if x.scheme!='https' or not x.hostname or x.username or x.password or x.query or x.fragment:
        raise ValueError('HTTPS configuration is required.')
    return value.rstrip('/')

def runtime_config(p):
    """Only the service operator can write this file and provision end-user bindings."""
    cfg=json.loads(p.read_text(encoding='utf-8-sig'))
    iss=https(cfg['issuer']); origin=https(cfg['origin'])
    if urlsplit(origin).path:raise ValueError('Use a dedicated origin per plugin.')
    jwks=https(cfg['jwks_uri'])
    exe=Path(cfg['runtime'])
    if not exe.is_absolute() or not exe.is_file():raise ValueError('Set the absolute backend runtime.')
    seen=set();homes=set();claims={}
    for subject,record in cfg['bindings'].items():
        if not subject.strip():raise ValueError('Empty identity binding.')
        uid=str(UUID(record['id']))
        home=Path(record['home'])
        if home.is_symlink() or not home.is_absolute() or not home.is_dir():raise ValueError('Set a private profile directory.')
        home=home.resolve()
        if uid in seen or any(home==h or h in home.parents or home in h.parents for h in homes):raise ValueError('Account IDs and homes must be distinct.')
        seen.add(uid);homes.add(home)
        env=record['env']
        if set(env)-set(SERVICE['keys']) or not all(isinstance(v,str) and v for v in env.values()) or set(SERVICE['required'])-set(env):
            raise ValueError('Invalid or incomplete provider environment.')
        for k in SERVICE.get('private_paths',[]):
            if k not in env:continue
            path=Path(env[k])
            if not path.is_absolute() or not path.resolve().is_relative_to(home) or not path.exists():
                raise ValueError('Put account credentials and browser state inside its own private home.')
        for k in SERVICE.get('url_keys',[]):
            if k in env:https(env[k])
        claims[subject]=(uid,str(record['label']),home,dict(env))
    if PRODUCT=='yxtown-study' and len({v[3]['YXTOWN_PORT'] for v in claims.values()})!=len(claims):
        raise ValueError('Each browser bridge requires a different loopback port.')
    return iss,origin,jwks,str(exe),claims


async def backend(exe,record):
    _uid,_label,home,params=record
    env={'HOME':str(home),'USERPROFILE':str(home),'XDG_CONFIG_HOME':str(home/'.config'),
         'XDG_DATA_HOME':str(home/'.local/share'),'XDG_CACHE_HOME':str(home/'.cache'),
         'APPDATA':str(home/'AppData/Roaming'),'LOCALAPPDATA':str(home/'AppData/Local'),**params}
    args=dict(SERVICE['args'])
    for key,env_key in SERVICE.get('bound_args',{}).items():args[key]=params[env_key]
    # No model input can select a command, URL, account, tool name, or parameters.
    transport=StdioTransport(command=exe,args=[str(ROOT/SERVICE['entry'])],env=env,
                             cwd=str(ROOT),keep_alive=False,log_file=os.devnull)
    async with asyncio.timeout(120):
        async with Client(transport,init_timeout=20) as c:
            result=await c.call_tool(SERVICE['tool'],args,raise_on_error=False)
            if result.is_error:raise ValueError('Connected backend could not complete its read.')
            if result.structured_content is not None:return result.structured_content
            return {'content':[part.text for part in result.content if part.type=='text']}


def build(p,*,test_public_key=None,runner=backend):
    issuer,origin,jwks,exe,bindings=runtime_config(p)
    aud=origin+'/mcp'
    verifier=JWTVerifier(issuer=issuer,audience=aud,algorithm='RS256',required_scopes=[SCOPE],
                         **({'public_key':test_public_key} if test_public_key is not None else {'jwks_uri':jwks,'ssrf_safe':True}))
    auth=RemoteAuthProvider(token_verifier=verifier,authorization_servers=[issuer],base_url=origin,scopes_supported=[SCOPE])
    m=FastMCP(PRODUCT,auth=auth,mask_error_details=True)
    def binding():
        token=get_access_token()
        if not token or token.claims.get('iss')!=issuer or not token.claims.get('exp') or token.claims.get('sub') not in bindings:
            raise ValueError('This identity has no local provider account binding.')
        return bindings[token.claims['sub']]
    @m.tool(name='connected_profile',output_schema=SCHEMA,meta={'openai/profile':True},annotations={'readOnlyHint':True})
    def profile()->dict[str,str]:
        """Identify the connected provider profile selected by this signed request."""
        uid,name,*_=binding()
        return {'id':uid,'name':name}
    @m.tool(name=SERVICE['tool'],description=SERVICE['description'],annotations={'readOnlyHint':True,'destructiveHint':False})
    async def read():
        """Read the provider data authorized for this profile."""
        return await runner(exe,binding())
    return m

if __name__=='__main__':
    server=build(Path(os.environ['CONNECTOR_BINDINGS_FILE']))
    uvicorn.run(server.http_app(path='/mcp',stateless_http=True,json_response=True),
                host='127.0.0.1',port=int(os.environ['CONNECTOR_LISTEN_PORT']),access_log=False)
