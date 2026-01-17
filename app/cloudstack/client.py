import httpx
from app.config import CLOUDSTACK

async def cs_request(command, params):
    params["command"] = command
    params["apikey"] = CLOUDSTACK["apikey"]
    params["response"] = "json"

    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(CLOUDSTACK["endpoint"], params=params)
        r.raise_for_status()
        return r.json()

