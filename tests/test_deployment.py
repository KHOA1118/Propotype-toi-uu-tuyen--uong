import json
import os
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from server import HTTPServer,Handler
from deployment_config import api_base_url,allowed_origins

class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.server=HTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_health_alias_and_public_config(self):
        with patch.dict(os.environ,{'API_BASE_URL':'https://api.example.test','PRIVATE_SECRET':'never-expose'}):
            self.assertEqual(json.load(urlopen(self.base+'/health')),{'status':'ok'})
            r=urlopen(self.base+'/config.js');body=r.read().decode()
            self.assertIn('text/javascript',r.headers['Content-Type']);self.assertIn('https://api.example.test',body)
            self.assertNotIn('never-expose',body)
    def test_exact_cors_allowlist_and_preflight(self):
        with patch.dict(os.environ,{'ALLOWED_ORIGINS':'https://demo.example.test'}):
            headers={'Origin':'https://demo.example.test','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'}
            r=urlopen(Request(self.base+'/api/reoptimize',method='OPTIONS',headers=headers))
            self.assertEqual(r.status,204);self.assertEqual(r.headers['Access-Control-Allow-Origin'],headers['Origin'])
            headers['Origin']='https://untrusted.example.test'
            with self.assertRaises(HTTPError) as failure:urlopen(Request(self.base+'/api/reoptimize',method='OPTIONS',headers=headers))
            self.assertEqual(failure.exception.code,403)
            r=urlopen(Request(self.base+'/health',headers={'Origin':headers['Origin']}))
            self.assertIsNone(r.headers.get('Access-Control-Allow-Origin'))
    def test_invalid_configuration_rejected(self):
        for value in ['javascript:alert(1)','https://name:password@example.test','https://example.test?a=1']:
            with patch.dict(os.environ,{'API_BASE_URL':value}):
                with self.assertRaises(ValueError):api_base_url()
        with patch.dict(os.environ,{'ALLOWED_ORIGINS':'*'}):
            with self.assertRaises(ValueError):allowed_origins()
