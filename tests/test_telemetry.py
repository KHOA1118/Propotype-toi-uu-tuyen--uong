import unittest
from road_network.telemetry import Traffic
from road_network.incidents import IncidentStore, IncidentError
from test_incidents import network

class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.network=network();self.store=IncidentStore();self.traffic=Traffic()
        self.sid=self.store.create({'source_sha256':'map-a'},self.network)['session_id']
        self.traffic.inject({'session_id':self.sid,'edge_id':'ab','expected_speed':.01},self.network,self.store)
    def sample(self,t,f):
        return self.traffic.sample({'session_id':self.sid,'samples':[{'vehicle_id':1,'edge_id':'ab','fraction':f,'time_ms':t}]},self.network,self.store)
    def test_hidden_until_two_consecutive_intervals(self):
        self.assertEqual(self.store.state(self.sid,self.network)['revision'],0)
        self.sample(0,0)
        self.assertEqual(self.sample(500,.01)['lifecycle'],'ACTIVE_UNDETECTED')
        result=self.sample(1000,.02)
        self.assertEqual(result['lifecycle'],'DETECTED')
        self.assertEqual(result['known_state']['edge_overrides']['ab']['travel_time_factor'],3)
        self.traffic.transition(self.sid,'REOPTIMIZING');self.traffic.transition(self.sid,'ROUTES_UPDATED')
        self.assertEqual(self.sample(1500,.03)['lifecycle'],'ROUTES_UPDATED')
        self.assertEqual(self.store.state(self.sid,self.network)['revision'],1)
    def test_duplicate_and_normal_sample_do_not_trigger(self):
        self.sample(0,0);self.sample(500,.01)
        self.assertEqual(self.sample(500,.01)['lifecycle'],'ACTIVE_UNDETECTED')
        self.sample(1000,.06)
        self.assertEqual(self.sample(1500,.07)['lifecycle'],'ACTIVE_UNDETECTED')
        self.assertEqual(self.sample(2000,.08)['lifecycle'],'DETECTED')
    def test_invalid_fraction_and_transition(self):
        with self.assertRaises(IncidentError):self.sample(500,1.1)
        with self.assertRaises(IncidentError):self.traffic.transition(self.sid,'ROUTES_UPDATED')
        with self.assertRaises(IncidentError):self.traffic.inject({'session_id':self.sid,'edge_id':'ab','expected_speed':1},self.network,self.store)
    def test_sparse_samples_cannot_claim_consecutive_slow_intervals(self):
        self.sample(0,0);self.sample(5000,.01)
        self.assertEqual(self.sample(5500,.02)['lifecycle'],'ACTIVE_UNDETECTED')
