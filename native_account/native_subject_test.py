# SPDX-License-Identifier: AGPL-3.0-only
"""Exercise the actual OAuth resource middleware with locally generated test identities."""
import asyncio,base64,json,secrets,sys,tempfile,time
from pathlib import Path
from uuid import uuid4
import httpx
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding,rsa
import account_http as mod

def make_jwt(key,payload):
    def enc(v):return base64.urlsafe_b64encode(v).decode().rstrip('=')
    raw=enc(b'{"alg":"RS256","typ":"JWT"}')+'.'+enc(json.dumps(payload).encode())
    return raw+'.'+enc(key.sign(raw.encode(),padding.PKCS1v15(),hashes.SHA256()))

async def test():
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    with tempfile.TemporaryDirectory() as d:
        root=Path(d); cfg=json.loads((Path(__file__).parent/'bindings.example.json').read_text(encoding='utf8'))
        sample=next(iter(cfg['bindings'].values()));cfg['runtime']=sys.executable;cfg['bindings']={}
        for i,subject in enumerate(('one','two')):
            home=root/subject;home.mkdir()
            env=dict(sample['env'])
            for field in mod.SERVICE.get('private_paths',[]):
                p=home/field.lower();p.touch();env[field]=str(p)
            if 'YXTOWN_PORT' in env:env['YXTOWN_PORT']=str(11001+i)
            cfg['bindings'][subject]={'id':str(uuid4()),'label':subject,'home':str(home),'env':env}
        p=root/'bindings.json';p.write_text(json.dumps(cfg),encoding='utf8')
        seen=[]
        async def fixture(_exe,record):
            seen.append(record[0]);return {'fixture':record[2].name}
        server=mod.build(p,test_public_key=public,runner=fixture)
        app=server.http_app(path='/mcp',stateless_http=True,json_response=True)
        origin=cfg['origin'];aud=origin+'/mcp'
        async with app.router.lifespan_context(app),httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url=origin) as c:
            meta=await c.get('/.well-known/oauth-protected-resource/mcp');assert meta.status_code==200 and meta.json()['resource']==aud
            async def call(subject,name,audience=aud,offset=90):
                token=make_jwt(key,{'iss':cfg['issuer'],'sub':subject,'aud':audience,'exp':int(time.time())+offset,'iat':int(time.time())-300,'scope':'connector.read','client_id':'fixture'})
                return await c.post('/mcp',headers={'Authorization':'Bearer '+token,'Accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':{}}})
            outputs=await asyncio.gather(*(call(sub,name) for sub in ('one','two') for name in ('connected_profile',mod.SERVICE['tool'])))
            for i,sub in enumerate(('one','two')):
                first=outputs[i*2].json()['result'];second=outputs[i*2+1].json()['result']
                assert first['structuredContent']['id']==cfg['bindings'][sub]['id']
                assert not second.get('isError') and sub in second['content'][0]['text']
            assert set(seen)=={r['id'] for r in cfg['bindings'].values()}
            unknown=await call('other',mod.SERVICE['tool']);assert unknown.json()['result']['isError'] and len(seen)==2
            assert (await call('one','connected_profile',audience=origin+'/other')).status_code==401
            assert (await call('two','connected_profile',offset=-120)).status_code==401
    print('PASS',mod.PRODUCT,'signed request isolation; unknown, expired and wrong-audience grants denied.')
if __name__=='__main__':asyncio.run(test())
