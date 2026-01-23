
# =========================
# Proxy Service (54323)
# =========================

proxy_app = FastAPI(title="oVirt ImageIO Proxy")

@proxy_app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path: str, request: Request):
    """
    Very simple proxy: forwards everything to 54322.
    In real oVirt, this handles host-network isolation.
    """
    import requests

    url = f"https://localhost:54322/{path}"

    headers = dict(request.headers)
    headers.pop("host", None)

    resp = requests.request(
        method=request.method,
        url=url,
        headers=headers,
        data=request.stream(),
        verify=False
    )

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )

def run_proxy():
    uvicorn.run(
        proxy_app,
        host="0.0.0.0",
        port=54323,
        ssl_keyfile="server.key",
        ssl_certfile="server.crt",
    )

if __name__ == "__main__":
    t2 = threading.Thread(target=run_proxy)
    t2.start()
    t2.join()
