"""One process worker, cached map per process, bounded job history. No framework."""
from concurrent.futures import ProcessPoolExecutor
from uuid import uuid4
from time import perf_counter
import os
from .store import NetworkStore
from .costs import context, initial_road_solution
from .reoptimization import reoptimize

_network = None


def initialize(source):
    global _network
    _network = NetworkStore(source).get()
    context(_network)


def execute(kind, payload, incidents):
    started = perf_counter()
    result = initial_road_solution(payload['scenario'], _network) if kind == 'initial' else reoptimize(payload, _network, incidents)
    return dict(result, worker_pid=os.getpid(), worker_seconds=perf_counter()-started)


class Jobs:
    def __init__(self, source):
        self.pool = ProcessPoolExecutor(max_workers=1, initializer=initialize, initargs=(str(source),))
        self.items = {}

    def submit(self, kind, payload, incidents=None):
        if sum(not v['future'].done() for v in self.items.values()) >= 4:
            raise ValueError('Worker queue full; retry shortly')
        for jid in list(self.items):
            if len(self.items) >= 100 and self.items[jid]['future'].done():
                del self.items[jid]
        jid = str(uuid4())
        self.items[jid] = {'future':self.pool.submit(execute,kind,payload,incidents), 'started':perf_counter(),
                           'session_id':payload.get('session_id'), 'revision':payload.get('revision')}
        return {'job_id':jid, 'status':'queued'}

    def status(self, jid):
        item = self.items.get(jid)
        if item is None:
            raise KeyError('Unknown job')
        future = item['future']
        if not future.done():
            return {'job_id':jid,'status':'running' if future.running() else 'queued'}
        try:
            return {'job_id':jid,'status':'completed','result':future.result()}
        except Exception as error:
            return {'job_id':jid,'status':'failed','error':str(error)}

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
