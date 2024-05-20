from fastapi import FastAPI, Request
from prometheus_client import start_http_server, Summary, Counter, Histogram, generate_latest, REGISTRY
from prometheus_client.core import CollectorRegistry
from starlette.responses import Response
import time

app = FastAPI()

# Создаем метрики
REQUEST_COUNT = Counter('http_requests_total', 'Total number of HTTP requests', ['method', 'endpoint'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['method', 'endpoint'])

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    method = request.method
    endpoint = request.url.path

    REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
    start_time = time.time()
    
    response = await call_next(request)
    
    latency = time.time() - start_time
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(latency)
    
    return response

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(REGISTRY), media_type="text/plain")

@app.get("/")
async def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
async def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}