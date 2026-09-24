"""Search fixed input configurations only; never edit a returned LNS route.

Run against the local app: python tools/design_root_scenario.py --node /path/to/node
Every accepted input must pass the real frontend Simulation + backend telemetry
and LNS pipeline in validate_presentation.cjs before either fixture is written.
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from road_network.store import NetworkStore
from road_network.costs import context, initial_road_solution
from road_network.routing import RoadRouter, separation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--base-url', default='http://127.0.0.1:8013')
    parser.add_argument('--start-seed', type=int, default=42)
    parser.add_argument('--end-seed', type=int, default=242)
    args = parser.parse_args()
    if not args.node:
        parser.error('Node.js is required to validate actual frontend timing; pass --node')
    root = Path(__file__).resolve().parents[1]
    network = NetworkStore(root/'data/raw/hcm_map4.osm').get()
    timed, router = context(network)
    component = router.demo_profile()['demo_node_ids']
    points = network['nodes']
    depot = min(component, key=lambda n: (separation(points[n], {'lat':10.746,'lon':106.700}), n))
    distances = router.tree(depot)[0]
    candidates = [n for n in component if points[n]['lon'] > points[depot]['lon']+.004
                  and 800 < separation(points[n], points[depot]) < 5000 and n in distances]
    environment = dict(os.environ, LNS_TEST_URL=args.base_url)

    def validate(fixture):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'candidate.json'
            source.write_text(json.dumps(fixture), encoding='utf-8')
            run = subprocess.run([args.node, str(root/'tools/validate_presentation.cjs'), str(source)],
                                 env=environment, capture_output=True, text=True, check=True, timeout=120)
            return json.loads(run.stdout)

    previous = json.loads((root/'data/presentation_scenario.json').read_text(encoding='utf-8'))
    baseline = validate(previous)
    print('Previous actual timing:', json.dumps(baseline), flush=True)
    for seed in range(args.start_seed, args.end_seed):
        rng = random.Random(seed)
        pool = sorted(rng.sample(sorted(candidates), min(250,len(candidates))))
        chosen = [max(pool, key=lambda n: (points[n]['lon'],n))]
        while len(chosen) < 24:
            chosen.append(max((n for n in pool if n not in chosen),
                              key=lambda n: (min(separation(points[n],points[k]) for k in chosen),n)))
        stops = [dict(id=i,osm_node_id=n,lat=points[n]['lat'],lon=points[n]['lon'],demand=10 if i else 0,
                      ready_time=0,due_date=100000,service_time=1 if i else 0) for i,n in enumerate([depot]+chosen)]
        scenario = {'vehicle_count':6,'vehicle_capacity':40,'options':{'seed':42,'iterations':80,'removal_count':5},'stops':stops}
        result = initial_road_solution(scenario, network)
        analysis, geo = result['overlap_analysis'], result['road_geometry']
        print('Candidate',seed,'corridors',analysis['shared_corridors'],flush=True)
        if not analysis['accepted'] or any(len(r)!=6 for r in result['routes']):
            continue
        speed = max(r['distance_m'] for r in geo['routes'])/(150000-4000)
        hotspots = []
        for edge in geo['overlap']['shared_edges']:
            if not 3 <= edge['routes_affected'] <= 4 or edge['baseline_distance_m'] < 80:
                continue
            if 5 not in edge['vehicles_affected'] or separation(points[depot],points[edge['from_node']]) < 600:
                continue
            # Cheap distance-based rejection only. The actual Simulation is the
            # acceptance authority, including dwell, physical delay and rerouting.
            arrival = {}
            for vehicle, route in enumerate(geo['routes'],1):
                if edge['edge_id'] in route['edge_ids']:
                    idx = route['edge_ids'].index(edge['edge_id'])
                    arrival[vehicle] = sum(timed['edges'][x]['distance'] for x in route['edge_ids'][:idx])/speed
            if min(arrival,key=arrival.get)!=5 or not 10000 < arrival[5] < 90000:
                continue
            if geo['routes'][1]['distance_m'] <= geo['routes'][4]['distance_m'] + 2*edge['baseline_distance_m'] + 300:
                continue
            reduced = dict(timed,edges={eid:e for eid,e in timed['edges'].items() if eid!=edge['edge_id']})
            if edge['to_node'] not in RoadRouter(reduced).tree(edge['from_node'])[0]:
                continue
            hotspots.append(edge)
        for edge in sorted(hotspots,key=lambda e:(-e['baseline_distance_m'],e['edge_id'])):
            raw = timed['edges'][edge['edge_id']]
            fixture = {'version':3,'source_sha256':network['metadata']['source']['sha256'],'configuration_seed':seed,
                'scenario':scenario,'duration_ms':150000,
                'event':{'type':'congestion','edge_id':edge['edge_id'],'incident_edge_id':edge['edge_id'],
                         'from_node':edge['from_node'],'to_node':edge['to_node'],
                         'baseline_travel_time':raw['travel_time'],'baseline_speed':raw['distance']/raw['travel_time'],
                         'vehicles_using_edge':edge['vehicles_affected'],'travel_time_multiplier':3.0,
                         'inject_at_ms':5000,'sample_interval_ms':500,'threshold':.5,'consecutive_samples':2},
                'design_validation':analysis}
            evidence = validate(fixture)
            print('Timing',seed,edge['edge_id'],json.dumps(evidence),flush=True)
            if not evidence['accepted']:
                continue
            changed = [{'id':new['id'],'old_osm_node_id':old['osm_node_id'],'new_osm_node_id':new['osm_node_id']}
                       for old,new in zip(previous['scenario']['stops'],stops) if old['osm_node_id']!=new['osm_node_id']]
            validation = {'overlap':geo['overlap'],'analysis':analysis,'depot':stops[0],
                          'initial_cost_seconds':result['objective'][1],**evidence,
                          'previous_scenario_timing':baseline,'changed_input_locations':changed}
            (root/'data/presentation_scenario.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            (root/'data/scenario_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('ACCEPTED',seed,edge['edge_id'],flush=True)
            return
    raise RuntimeError('No accepted deterministic input configuration; fixtures unchanged')

if __name__ == '__main__':
    main()
