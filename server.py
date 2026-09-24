"""Milestone 2 local HTTP server. Run: python server.py"""
import argparse
import os
from deployment_config import api_base_url, allowed_origins
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import traceback

from lns.adapter import solve_instance, validate_request, InputError, ConstructionError
from road_network.loader import MapValidationError
from road_network.store import NetworkStore
from road_network.routing import RoadRouter, RoutingError
from road_network.incidents import IncidentStore, IncidentError
from road_network.reoptimization import reoptimize
from road_network.jobs import Jobs
from road_network.telemetry import Traffic
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).resolve().parent
MAX_BODY_BYTES = 32 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if origin not in allowed_origins():
            return self.reply(403, {"error": "Origin is not allowed"})
        if self.headers.get("Access-Control-Request-Method") not in ("GET", "POST"):
            return self.reply(405, {"error": "Method is not allowed"})
        requested = {s.strip().lower() for s in self.headers.get("Access-Control-Request-Headers", "").split(",") if s.strip()}
        if requested - {"content-type"}:
            return self.reply(403, {"error": "Header is not allowed"})
        return self.reply(204, b"")

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def jobs(self):
        if not hasattr(self.server, "jobs"):
            self.server.jobs = Jobs(self.server.network_store.source)
        return self.server.jobs

    def traffic(self):
        if not hasattr(self.server, "traffic"):
            self.server.traffic = Traffic()
        return self.server.traffic

    def incident_store(self):
        if not hasattr(self.server, 'incident_store'):
            self.server.incident_store = IncidentStore()
        return self.server.incident_store

    def incident_request(self, payload=None):
        store = getattr(self.server, 'network_store', None)
        if store is None:
            return self.reply(503, {'error': 'Map source is not configured'})
        try:
            network = store.get()
            incidents = self.incident_store()
            if payload is None:
                sid = parse_qs(urlsplit(self.path).query).get('session_id', [''])[0]
                result = incidents.state(sid, network)
            elif self.path == '/api/simulation':
                result = incidents.create(payload, network)
            else:
                result = incidents.report(payload, network)
            return self.reply(200, result)
        except (IncidentError, MapValidationError) as error:
            return self.reply(400, {'error': str(error)})
        except (FileNotFoundError, PermissionError):
            return self.reply(503, {'error': 'Map source is unavailable'})

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if isinstance(payload, dict) else payload
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Vary", "Origin")
            origin = getattr(self, "headers", {}).get("Origin")
            if origin and origin in allowed_origins():
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            # A browser timeout/tab close is not a solver failure.
            self.close_connection = True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith('/api/jobs/'):
            try:
                jid=path.rsplit('/',1)[1]
                result=self.jobs().status(jid)
                item=self.jobs().items[jid]
                if item['session_id']:
                    current=self.incident_store().state(item['session_id'],self.server.network_store.get())
                    if current['revision'] != item['revision']:
                        return self.reply(200,{'job_id':jid,'status':'failed','error':'Stale incident revision'})
                return self.reply(200,result)
            except KeyError:
                return self.reply(404,{'error':'Unknown job'})
        if path == "/config.js":
            script = "window.APP_CONFIG = " + json.dumps({"API_BASE_URL": api_base_url()}) + ";\n"
            return self.reply(200, script.encode(), "text/javascript; charset=utf-8")
        if path in ("/health", "/api/health"):
            return self.reply(200, {"status": "ok"})
        if path == '/api/simulation':
            return self.incident_request()
        if path == '/api/presentation-scenario':
            try:
                fixture = json.loads((ROOT / 'data/presentation_scenario.json').read_text(encoding='utf-8'))
                network = self.server.network_store.get()
                if fixture['source_sha256'] != network['metadata']['source']['sha256']:
                    return self.reply(422, {'error': 'Presentation scenario requires the supplied HCM map'})
                if fixture['event']['edge_id'] not in network['edges'] or any(s['osm_node_id'] not in network['nodes'] for s in fixture['scenario']['stops']):
                    return self.reply(422, {'error': 'Presentation scenario contains missing road references'})
                return self.reply(200, fixture)
            except (OSError, ValueError, AttributeError, KeyError) as error:
                return self.reply(503, {'error': f'Presentation scenario unavailable: {error}'})
        network_routes = {"/api/network/context": "context", "/api/network": "network", "/api/network/metadata": "metadata", "/api/network/geojson": "geojson", "/api/network/routing-profile": "routing-profile", "/api/demo-scenario": "demo-scenario"}
        if path in network_routes:
            store = getattr(self.server, "network_store", None)
            if store is None:
                return self.reply(503, {"error": "Map source is not configured"})
            try:
                router = RoadRouter(store.get()) if network_routes[path] in ("routing-profile", "demo-scenario") else None
                network = (router.demo_profile() if network_routes[path] == 'routing-profile' else
                           router.presentation_scenario() if network_routes[path] == 'demo-scenario' else
                           store.get(network_routes[path]))
            except (FileNotFoundError, PermissionError):
                return self.reply(503, {"error": "Map source is unavailable; configure --map-data"})
            except (MapValidationError, RoutingError) as error:
                return self.reply(422, {"error": str(error)})
            return self.reply(200, network)
        if path == "/example.json":
            return self.reply(200, (ROOT / "data/example_request.json").read_bytes())
        files = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/dashboard.js": ("dashboard.js", "text/javascript"), "/presentation.js": ("presentation.js", "text/javascript"), "/map-data.js": ("map-data.js", "text/javascript"), "/simulation.js": ("simulation.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
        if path not in files:
            return self.reply(404, {"error": "Not found"})
        name, mime = files[path]
        self.reply(200, (ROOT / "frontend" / name).read_bytes(), mime + "; charset=utf-8")

    def do_POST(self):
        if self.path not in ("/api/optimize", "/api/network/routes", "/api/simulation", "/api/incidents", "/api/reoptimize", "/api/jobs/initial", "/api/traffic/inject", "/api/traffic/telemetry", "/api/traffic/applied"):
            return self.reply(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY_BYTES:
                raise ValueError("Request body must contain 1–33554432 bytes")
            payload = json.loads(self.rfile.read(length))
            if self.path in ('/api/jobs/initial','/api/reoptimize'):
                try:
                    incidents=None
                    if self.path == '/api/reoptimize':
                        incidents=self.incident_store().state(payload['session_id'],self.server.network_store.get())
                        if payload['revision'] != incidents['revision']:
                            raise ValueError('Stale incident revision')
                        event=self.traffic().events.get(payload['session_id'])
                        if event and event['lifecycle']=='ACTIVE_UNDETECTED':
                            raise ValueError('Traffic has not been detected; no reoptimization allowed')
                    job=self.jobs().submit('initial' if incidents is None else 'dynamic',payload,incidents)
                    if incidents and self.traffic().events.get(payload['session_id'],{}).get('lifecycle')=='DETECTED':
                        self.traffic().transition(payload['session_id'],'REOPTIMIZING')
                    return self.reply(202,job)
                except (ValueError,KeyError,TypeError,AttributeError) as error:
                    return self.reply(422,{'error':str(error)})
            if self.path.startswith('/api/traffic/'):
                try:
                    network=self.server.network_store.get()
                    if self.path.endswith('/inject'):
                        result=self.traffic().inject(payload,network,self.incident_store())
                    elif self.path.endswith('/telemetry'):
                        result=self.traffic().sample(payload,network,self.incident_store())
                    else:
                        current=self.incident_store().state(payload['session_id'],network)
                        job=self.jobs().status(payload['job_id'])
                        item=self.jobs().items[payload['job_id']]
                        if item['revision']!=current['revision'] or item['session_id']!=payload['session_id'] or job['status']!='completed' or job['result']['failures']:
                            raise ValueError('No successful solution for this session')
                        self.traffic().transition(payload['session_id'],'ROUTES_UPDATED')
                        result={'lifecycle':'ROUTES_UPDATED'}
                    return self.reply(200,result)
                except (ValueError,KeyError,TypeError) as error:
                    return self.reply(422,{'error':str(error)})
            if self.path in ('/api/simulation', '/api/incidents'):
                if not isinstance(payload, dict):
                    raise ValueError('Expected JSON object')
                return self.incident_request(payload)
            if self.path == "/api/network/routes":
                store = getattr(self.server, 'network_store', None)
                if store is None:
                    return self.reply(503, {'error': 'Map source is not configured'})
                try:
                    return self.reply(200, RoadRouter(store.get()).route(payload))
                except (RoutingError, MapValidationError) as error:
                    return self.reply(422, {'error': str(error)})
                except (FileNotFoundError, PermissionError):
                    return self.reply(503, {'error': 'Map source is unavailable'})
            validate_request(payload)
        except (ValueError, UnicodeDecodeError) as error:
            return self.reply(400, {"error": str(error)})
        try:
            result = solve_instance(**payload)
        except InputError as error:
            return self.reply(400, {"error": str(error)})
        except ConstructionError as error:
            return self.reply(422, {"error": str(error)})
        except Exception:
            traceback.print_exc()
            return self.reply(500, {"error": "LNS failed. See the server terminal."})
        self.reply(200, result)


def parse_server_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--map-data", type=Path, default=Path(os.getenv("MAP_DATA", str(ROOT / "data/raw/hcm_map4.osm"))))
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_server_args()
    api_base_url(); allowed_origins()
    server = HTTPServer((args.host, args.port), Handler)
    server.timeout = 15
    server.network_store = NetworkStore(args.map_data)
    host, port = server.server_address
    print(f"Listening on {host}:{port}", flush=True)
    print(f"Open http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}/ (keep this process running)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if hasattr(server,"jobs"):
            server.jobs.close()
