import copy
import unittest
from unittest.mock import patch
from road_network.reoptimization import reoptimize
from road_network.routing import RoutingError
from lns.adapter import solve_instance
from test_routing import network


def fixture():
    n = network()
    for eid, a, b in [('13','1','3'), ('32','3','2'), ('20','2','0')]:
        n['edges'][eid] = dict(n['edges']['0'], id=eid, from_node=a, to_node=b, distance=150)
    stops = [dict(n['nodes'][str(i)], id=sid, demand=0 if i==0 else 10,
                  ready_time=0, due_date=10000, service_time=0 if i==0 else 1)
             for i,sid in enumerate([0,11,22,33])]
    state = {'revision':1, 'edge_overrides':{'1':{'available':True,'travel_time_factor':6}}}
    p = {'revision':1, 'scenario':{'stops':stops,'vehicle_count':1,'vehicle_capacity':30,
                                 'options':{'seed':42,'iterations':60,'removal_count':2}},
         'vehicles':[{'route_index':0,'assigned':[11,22,33],'served':[], 'anchor':11,
                      'remaining':[22,33], 'ready_time':50, 'suffix_edge_ids':['1','2','3'],
                      'committed_edge_ids':['0']}]}
    return n,state,p


class ReoptimizationTests(unittest.TestCase):
    def test_current_road_node_is_virtual_start_and_not_a_customer(self):
        n,s,p=fixture(); v=p['vehicles'][0]
        v.update(served=[11],anchor=-1,anchor_osm_node_id='1',remaining=[22,33])
        u=reoptimize(p,n,s)['updates'][0]
        self.assertEqual(u['geometry']['node_ids'][0],'1')
        self.assertEqual(u['geometry']['stop_sequence'][0],-1)
        self.assertEqual(u['order'],[33,22])
        self.assertEqual([n['id'] for n in u['solver']['dataset']['nodes']],[0,22,33])

    def test_real_lns_road_costs_virtual_start_metrics_and_ownership(self):
        n,s,p=fixture(); original=copy.deepcopy(n)
        with patch('road_network.reoptimization.solve_instance', wraps=solve_instance) as real:
            result=reoptimize(p,n,s)
        self.assertFalse(result['failures']); self.assertEqual(real.call_count,1)
        u=result['updates'][0]
        self.assertEqual(u['engine'],'original-lns'); self.assertTrue(u['solver']['feasible'])
        self.assertEqual(u['order'],[33,22]); self.assertEqual(u['solver']['iterations_completed'],60)
        self.assertEqual(u['solver']['matrix_sources'],{'distance':'provided','travel_time':'provided'})
        self.assertAlmostEqual(u['solver']['objective'][1],u['metrics']['after'])
        self.assertLess(u['metrics']['after'],u['metrics']['before'])
        self.assertEqual(u['geometry']['node_ids'],['1','3','2','0'])
        self.assertEqual(n,original)
        for seed in [1,42,99]:
            p['scenario']['options']['seed']=seed
            a=reoptimize(p,n,s); b=reoptimize(p,n,s)
            self.assertEqual(a['updates'][0]['order'],b['updates'][0]['order'])

    def test_served_customer_excluded_and_blocked_edge_avoided(self):
        n,s,p=fixture(); v=p['vehicles'][0]
        v.update(served=[11],anchor=22,remaining=[33],suffix_edge_ids=['2','3'],committed_edge_ids=['1'])
        s['edge_overrides']={'2':{'available':False}}
        # A detour exists via depot -> 1 -> 3, and cannot include blocked edge 2.
        u=reoptimize(p,n,s)['updates'][0]
        self.assertEqual(u['order'],[33]); self.assertNotIn('2',u['geometry']['edge_ids'])
        self.assertIsNone(u['metrics']['before']); self.assertFalse(u['metrics']['before_available'])
        self.assertEqual([x['id'] for x in u['solver']['dataset']['nodes']],[0,33])

    def test_invalid_partition_stale_revision_and_geometry(self):
        for change in [{'served':[22]}, {'remaining':[22,22]}, {'assigned':[11,22,33,99]}]:
            n,s,p=fixture(); p['vehicles'][0].update(change)
            with self.assertRaises(RoutingError): reoptimize(p,n,s)
        n,s,p=fixture(); p['revision']=0
        with self.assertRaisesRegex(RoutingError,'Stale'): reoptimize(p,n,s)
        p['revision']=1; p['vehicles'][0]['suffix_edge_ids']=['3','1']
        self.assertTrue(reoptimize(p,n,s)['failures'])

    def test_capacity_windows_depot_and_unreachable_fail_without_fake_result(self):
        for field in ['capacity','window','depot','unreachable','committed']:
            n,s,p=fixture()
            if field=='capacity':
                p['scenario']['vehicle_capacity']=10
                p['scenario']['vehicle_count']=3
            if field=='window': p['scenario']['stops'][2]['due_date']=1
            if field=='depot': p['scenario']['stops'][0]['due_date']=1
            if field=='unreachable': s['edge_overrides'].update({e:{'available':False} for e in ['1','13']})
            if field=='committed': s['edge_overrides']['0']={'available':False}
            result=reoptimize(p,n,s)
            self.assertFalse(result['updates'],field); self.assertTrue(result['failures'],field)

    def test_unaffected_all_served_and_return_only(self):
        n,s,p=fixture(); s['edge_overrides']={}
        with patch('road_network.reoptimization.solve_instance',wraps=solve_instance) as real:
            self.assertFalse(reoptimize(p,n,s)['updates']); real.assert_not_called()
        v=p['vehicles'][0]; v.update(served=[11,22],anchor=33,remaining=[],suffix_edge_ids=['3'])
        s['edge_overrides']={'3':{'available':True,'travel_time_factor':3}}
        self.assertEqual(reoptimize(p,n,s)['updates'][0]['engine'],'road-return-only')
        v.update(served=[11,22,33],anchor=0,suffix_edge_ids=[])
        self.assertFalse(reoptimize(p,n,s)['updates'])
