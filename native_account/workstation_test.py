import asyncio,base64,hashlib,secrets,json,sys,tempfile,os
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import httpx
from workstation_apps import build
root=Path(__file__).resolve().parent.parent
cfg={"products":{"primary":str(root)},"origin":"https://bridge.example.org","approval_port":18642}
async def test():
 with tempfile.TemporaryDirectory() as tmp:
  cfg['state_dir']=tmp
  async def invoke(url,token,name):
   return await cli.post(url,headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':name,'arguments':{}}})
  fake=lambda p:{a:{'id':'id_'+p+a,'name':a,'alias':a,'fingerprint':a} for a in ('one','two')}
  with patch('workstation_apps.profiles',fake):
   public,approval=build(cfg)
   async with public.router.lifespan_context(public),httpx.AsyncClient(transport=httpx.ASGITransport(app=public),base_url=cfg['origin']) as cli:
    for slug in cfg['products']:
     path='/codex-accounts/'+slug
     meta=await cli.get('/.well-known/oauth-authorization-server'+path)
     assert meta.status_code==200,(meta.status_code,path)
     url=cfg['origin']+path+'/mcp'
     cb='https://chatgpt.com/connector_platform_oauth_redirect'
     reg=await cli.post(path+'/register',json={'client_name':'Read test','redirect_uris':[cb],'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'token_endpoint_auth_method':'none','scope':'connector.read'})
     assert reg.status_code==201,(reg.status_code,reg.text[:130])
     client=reg.json()['client_id']
     for alias in ('one','two'):
      verifier=secrets.token_urlsafe(48);challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
      req=await cli.get(path+'/authorize',params={'client_id':client,'redirect_uri':cb,'response_type':'code','scope':'connector.read','state':'test','resource':url,'code_challenge':challenge,'code_challenge_method':'S256'})
      assert req.is_redirect,(req.status_code,req.text[:100])
      target=req.headers['location'];pk={k:v[0] for k,v in parse_qs(urlsplit(target).query).items()}
      private='http://127.0.0.1:'+str(cfg['approval_port'])
      async with httpx.AsyncClient(transport=httpx.ASGITransport(app=approval),base_url=private) as desk:
       page=await desk.get(target);assert page.status_code==200
       csrf=next(v for k,v in desk.cookies.items() if k.startswith('ldai_approval_'))
       body={**pk,'csrf':csrf,'op':'approve','profile':alias}
       blocked=await desk.post('/choose',data=body,headers={'Origin':'https://example.invalid'});assert blocked.status_code==400
       yes=await desk.post('/choose',data=body,headers={'Origin':private});assert yes.is_redirect
      code=parse_qs(urlsplit(yes.headers['location']).query)['code'][0]
      args={'grant_type':'authorization_code','client_id':client,'code':code,'code_verifier':verifier,'redirect_uri':cb,'resource':url}
      token=await cli.post(path+'/token',data=args); assert token.status_code==200,token.text[:120]
      auth=token.json();got=await invoke(url,auth['access_token'],'connected_profile')
      assert got.status_code==200 and got.json()['result']['structuredContent']['name']==alias
      reuse=await cli.post(path+'/token',data=args);assert reuse.status_code!=200
      wrong='/codex-accounts/unknown/mcp'
      assert (await invoke(wrong,auth['access_token'],'connected_profile')).status_code==404
      renewed=await cli.post(path+'/token',data={'grant_type':'refresh_token','client_id':client,'refresh_token':auth['refresh_token']})
      assert renewed.status_code==200,renewed.text[:100]
     print('PASS',slug,'two browser grants and resource isolation')
asyncio.run(test())
