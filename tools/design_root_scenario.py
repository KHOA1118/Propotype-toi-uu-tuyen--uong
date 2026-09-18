"""Search fixed input configurations only; never edit a returned LNS route."""
import json
import math
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from road_network.store import NetworkStore
from road_network.costs import context, initial_road_solution
from road_network.routing import RoadRouter, separation

root=Path(__file__).resolve().parents[1]
network=NetworkStore(root/'data/raw/hcm_map4.osm').get()
timed,router=context(network)
component=router.demo_profile()['demo_node_ids']
points=network['nodes']
# Southwest border of the same strongly-connected operational region.
depot=min(component,key=lambda n:(separation(points[n],{'lat':10.746,'lon':106.700}),n))
print('depot',depot,points[depot],flush=True)
distances=router.tree(depot)[0]
candidates=[n for n in component if points[n]['lon']>points[depot]['lon']+.004 and
            800<separation(points[n],points[depot])<5000 and n in distances]
for seed in range(42,62):
    rng=random.Random(seed)
    pool=sorted(rng.sample(sorted(candidates),min(250,len(candidates))))
    chosen=[max(pool,key=lambda n:(points[n]['lon'],n))]
    while len(chosen)<24:
        chosen.append(max((n for n in pool if n not in chosen),
            key=lambda n:(min(separation(points[n],points[k]) for k in chosen),n)))
    stops=[dict(id=i,osm_node_id=n,lat=points[n]['lat'],lon=points[n]['lon'],demand=10 if i else 0,
                ready_time=0,due_date=100000,service_time=1 if i else 0) for i,n in enumerate([depot]+chosen)]
    scenario={'vehicle_count':6,'vehicle_capacity':40,'options':{'seed':42,'iterations':80,'removal_count':5},'stops':stops}
    result=initial_road_solution(scenario,network)
    analysis=result['overlap_analysis'];geo=result['road_geometry']
    print(seed,analysis['shared_corridors'],analysis['maximum_edge_users'],flush=True)
    if not analysis['accepted'] or any(not 3<=len(r)-2<=5 for r in result['routes']):continue
    speed=max(r['distance_m'] for r in geo['routes'])/(150000-4000)
    hotspots=[]
    for e in geo['overlap']['shared_edges']:
        if not 3<=e['routes_affected']<=4 or e['baseline_distance_m']<80:continue
        if separation(points[depot],points[e['from_node']])<600:continue
        arrival=[]
        for r in geo['routes']:
            if e['edge_id'] in r['edge_ids']:
                idx=r['edge_ids'].index(e['edge_id'])
                arrival.append(sum(timed['edges'][x]['distance'] for x in r['edge_ids'][:idx])/speed)
        if min(arrival)<10000 or min(arrival)>90000:continue
        reduced=dict(timed,edges={eid:edge for eid,edge in timed['edges'].items() if eid!=e['edge_id']})
        alternate=RoadRouter(reduced)
        if e['to_node'] not in alternate.tree(e['from_node'])[0]:continue
        hotspots.append((e,arrival))
    if not hotspots:continue
    e,arrival=max(hotspots,key=lambda item:(item[0]['baseline_distance_m'],item[0]['edge_id']))
    edge=timed['edges'][e['edge_id']]
    fixture={'version':2,'source_sha256':network['metadata']['source']['sha256'],'configuration_seed':seed,
        'scenario':scenario,'duration_ms':150000,
        'event':{'type':'congestion','edge_id':e['edge_id'],'incident_edge_id':e['edge_id'],'from_node':e['from_node'],
                 'to_node':e['to_node'],'baseline_travel_time':edge['travel_time'],
                 'baseline_speed':edge['distance']/edge['travel_time'],'vehicles_using_edge':e['vehicles_affected'],
                 'travel_time_multiplier':3.0,'inject_at_ms':5000,'sample_interval_ms':500,'threshold':.5,'consecutive_samples':2},
        'design_validation':analysis}
    (root/'data/presentation_scenario.json').write_text(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (root/'data/scenario_validation.json').write_text(json.dumps({'overlap':geo['overlap'],'analysis':analysis,'depot':stops[0],
        'initial_cost_seconds':result['objective'][1],'customer_counts':[len(r)-2 for r in result['routes']],
        'hotspot_arrival_ms':arrival},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('ACCEPTED',seed,e['edge_id'],e['vehicles_affected'],arrival,flush=True)
    break
else:raise RuntimeError('No accepted deterministic input configuration found')
