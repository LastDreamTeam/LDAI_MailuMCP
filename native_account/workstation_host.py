import asyncio,json,sys
from pathlib import Path
import uvicorn
from workstation_apps import build
async def start(config):
    public,approval=build(config)
    servers=[uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=config[key],access_log=False,log_level="warning",proxy_headers=False)) for key,app in (("service_port",public),("approval_port",approval))]
    jobs=[asyncio.create_task(s.serve()) for s in servers]
    try:await asyncio.wait(jobs,return_when=asyncio.FIRST_COMPLETED)
    finally:
        for s in servers:s.should_exit=True
        await asyncio.gather(*jobs)
if __name__=="__main__":asyncio.run(start(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))))
