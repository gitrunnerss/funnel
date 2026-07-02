"""
Runner Control - minimal FastAPI backend (iskelet).

Gorevi:
  - Panelden gelen "baslat" istegini GitHub'a workflow_dispatch olarak iletir.
  - Her run icin benzersiz correlation_id uretir (workflow_dispatch run_id dondurmedigi
    icin eslestirme bununla yapilir).
  - Runner'lardan gelen /webhook/tunnel POST'unu alir (tunel URL'leri).
  - Panel bu backend'i GET /runners ile poll eder.

Calistirma (Codespace icinde):
  pip install fastapi uvicorn httpx
  export GH_TOKEN=ghp_xxx GH_OWNER=cihandurmus GH_REPO=vm-runners WEBHOOK_SECRET=super-secret
  uvicorn main:app --host 0.0.0.0 --port 8000

Backend'in runner'dan erisilebilir (public) olmasi gerekir: Codespace portunu
"public" yap veya backend'e ayri bir cloudflared tunel ac ve BACKEND_URL olarak workflow'a ver.
"""
import os, uuid, time
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

GH_TOKEN = os.environ["GH_TOKEN"]
OWNER, REPO = os.environ["GH_OWNER"], os.environ["GH_REPO"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "change-me")
GH_API = "https://api.github.com"

app = FastAPI(title="Runner Control")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Basit in-memory state (20 makine icin fazlasiyla yeterli).
RUNNERS: dict[str, dict] = {}

WORKFLOW_BY_OS = {"linux": "kasm-linux.yml", "win": "windows-vnc.yml"}


class LaunchReq(BaseModel):
    os: str = "linux"                 # linux | win
    image: str = "kasmweb/desktop:1.18.0"
    tunnel_provider: str = "cloudflare"
    duration_minutes: int = 60
    vnc_password: str = "kasm_password_123"
    count: int = 1


def gh_headers():
    return {"Authorization": f"Bearer {GH_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


@app.post("/runners")
async def launch(req: LaunchReq):
    wf = WORKFLOW_BY_OS.get(req.os)
    if not wf:
        raise HTTPException(400, "bilinmeyen os")
    created = []
    async with httpx.AsyncClient(timeout=20) as c:
        for _ in range(max(1, min(20, req.count))):
            cid = uuid.uuid4().hex[:8]
            inputs = {
                "correlation_id": cid,
                "sure_dakika": str(req.duration_minutes),
                "vnc_sifre": req.vnc_password,
                "tunnel_provider": req.tunnel_provider,
            }
            if req.os == "linux":
                inputs["image"] = req.image
            r = await c.post(
                f"{GH_API}/repos/{OWNER}/{REPO}/actions/workflows/{wf}/dispatches",
                headers=gh_headers(),
                json={"ref": "main", "inputs": inputs},
            )
            if r.status_code >= 300:
                raise HTTPException(502, f"github dispatch hatasi: {r.text}")
            RUNNERS[cid] = {
                "id": f"desktop-{cid[:4]}", "correlation_id": cid, "os": req.os,
                "image": req.image, "tunnel": req.tunnel_provider,
                "duration": req.duration_minutes * 60, "pwd": req.vnc_password,
                "status": "booting", "vnc_url": None, "files_url": None,
                "started_at": time.time(), "run_id": None,
            }
            created.append(cid)
    return {"launched": created}


@app.get("/runners")
async def list_runners():
    # run_id eslestirme: workflow_dispatch run_id dondurmez, run adina yazdigimiz
    # correlation_id ile eslestiririz. (Opsiyonel: burada actions/runs cekilip guncellenir.)
    return {"runners": list(RUNNERS.values())}


class TunnelHook(BaseModel):
    correlation_id: str
    status: str = "ready"
    os: Optional[str] = None
    vnc_url: Optional[str] = None
    files_url: Optional[str] = None
    user: Optional[str] = None


@app.post("/webhook/tunnel")
async def tunnel_hook(hook: TunnelHook, x_webhook_token: str = Header(default="")):
    if x_webhook_token != WEBHOOK_SECRET:
        raise HTTPException(401, "gecersiz token")
    m = RUNNERS.get(hook.correlation_id)
    if not m:
        # panel yeniden baslatildiysa kaydi olustur
        m = RUNNERS[hook.correlation_id] = {"id": f"desktop-{hook.correlation_id[:4]}",
                                            "correlation_id": hook.correlation_id,
                                            "started_at": time.time()}
    m.update({k: v for k, v in hook.model_dump().items() if v is not None})
    return {"ok": True}


async def _find_run_id(c: httpx.AsyncClient, cid: str) -> Optional[int]:
    r = await c.get(f"{GH_API}/repos/{OWNER}/{REPO}/actions/runs",
                    headers=gh_headers(), params={"event": "workflow_dispatch", "per_page": 50})
    for run in r.json().get("workflow_runs", []):
        if cid in (run.get("name") or ""):
            return run["id"]
    return None


@app.delete("/runners/{cid}")
async def stop(cid: str):
    m = RUNNERS.get(cid)
    if not m:
        raise HTTPException(404, "bulunamadi")
    async with httpx.AsyncClient(timeout=20) as c:
        run_id = m.get("run_id") or await _find_run_id(c, cid)
        if run_id:
            await c.post(f"{GH_API}/repos/{OWNER}/{REPO}/actions/runs/{run_id}/cancel",
                         headers=gh_headers())
    m["status"] = "stopped"
    return {"ok": True}
