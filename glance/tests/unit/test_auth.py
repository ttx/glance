# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack, LLC
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import json
import stubout
import webob

from glance.common import auth
from glance.common import exception
from glance.tests import utils


class FakeResponse(object):
    """
    Simple class that masks the inconsistency between
    webob.Response.status_int and httplib.Response.status
    """
    def __init__(self, resp):
        self.resp = resp

    def __getitem__(self, key):
        return self.resp.headers.get(key)

    @property
    def status(self):
        return self.resp.status_int


class V2Token(object):
    def __init__(self):
        self.tok = self.base_token

    def add_service_no_type(self):
        catalog = self.tok['access']['serviceCatalog']
        service_type = {"name": "glance_no_type"}
        catalog.append(service_type)
        service = catalog[-1]
        service['endpoints'] = [self.base_endpoint]

    def add_service(self, s_type, region_list=[]):
        catalog = self.tok['access']['serviceCatalog']
        service_type = {"type": s_type, "name": "glance"}
        catalog.append(service_type)
        service = catalog[-1]
        endpoint_list = []

        if region_list == []:
            endpoint_list.append(self.base_endpoint)
        else:
            for region in region_list:
                endpoint = self.base_endpoint
                endpoint['region'] = region
                endpoint_list.append(endpoint)

        service['endpoints'] = endpoint_list

    @property
    def token(self):
        return self.tok

    @property
    def base_endpoint(self):
        return {
            "adminURL": "http://localhost:9292",
            "internalURL": "http://localhost:9292",
            "publicURL": "http://localhost:9292"
    }

    @property
    def base_token(self):
        return {
            "access": {
                "token": {
                    "expires": "2010-11-23T16:40:53.321584",
                    "id": "5c7f8799-2e54-43e4-851b-31f81871b6c",
                    "tenant": {"id": "1", "name": "tenant-ok"}
                },
                "serviceCatalog": [
                ],
                "user": {
                    "id": "2",
                    "roles": [{
                        "tenantId": "1",
                        "id": "1",
                        "name": "Admin"
                    }],
                    "name": "joeadmin"
                }
            }
        }


class TestKeystoneAuthPlugin(utils.BaseTestCase):
    """Test that the Keystone auth plugin works properly"""

    def setUp(self):
        super(TestKeystoneAuthPlugin, self).setUp()
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        super(TestKeystoneAuthPlugin, self).tearDown()
        self.stubs.UnsetAll()

    def test_required_creds(self):
        """
        Test that plugin created without required
        credential pieces raises an exception
        """
        bad_creds = [
            {},  # missing everything
            {
                'username': 'user1',
                'password': 'pass'
            },  # missing auth_url
            {
                'password': 'pass',
                'auth_url': 'http://localhost/v1'
            },  # missing username
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v1'
            },  # missing password
            {
                'username': 'user1',
                'password': 'pass',
                'auth_url': 'http://localhost/v2.0/'
            }  # v2.0: missing tenant
        ]
        for creds in bad_creds:
            try:
                plugin = auth.KeystoneStrategy(creds)
                plugin.authenticate()
                self.fail("Failed to raise correct exception when supplying "
                          "bad credentials: %r" % creds)
            except exception.MissingCredentialError:
                continue  # Expected

    def test_invalid_auth_url_v1(self):
        """
        Test that a 400 during authenticate raises exception.AuthBadRequst
        """
        def fake_do_request(*args, **kwargs):
            resp = webob.Response()
            resp.status = 400
            return FakeResponse(resp), ""

        self.stubs.Set(auth.KeystoneStrategy, '_do_request', fake_do_request)

        bad_creds = {
            'username': 'user1',
            'auth_url': 'http://localhost/badauthurl/',
            'password': 'pass',
            'strategy': 'keystone',
            'region': 'RegionOne'
        }

        plugin = auth.KeystoneStrategy(bad_creds)
        self.assertRaises(exception.AuthBadRequest, plugin.authenticate)

    def test_invalid_auth_url_v2(self):
        """
        Test that a 400 during authenticate raises exception.AuthBadRequst
        """
        def fake_do_request(*args, **kwargs):
            resp = webob.Response()
            resp.status = 400
            return FakeResponse(resp), ""

        self.stubs.Set(auth.KeystoneStrategy, '_do_request', fake_do_request)

        bad_creds = {
            'username': 'user1',
            'auth_url': 'http://localhost/badauthurl/v2.0/',
            'password': 'pass',
            'tenant': 'tenant1',
            'strategy': 'keystone',
            'region': 'RegionOne'
        }

        plugin = auth.KeystoneStrategy(bad_creds)
        self.assertRaises(exception.AuthBadRequest, plugin.authenticate)

    def test_v1_auth(self):
        """Test v1 auth code paths"""
        def fake_do_request(cls, url, method, headers=None, body=None):
            if url.find("2.0") != -1:
                self.fail("Invalid v1.0 token path (%s)" % url)
            headers = headers or {}

            resp = webob.Response()

            if (headers.get('X-Auth-User') != 'user1' or
                headers.get('X-Auth-Key') != 'pass'):
                resp.status = 401
            else:
                resp.status = 200

            return FakeResponse(resp), ""

        self.stubs.Set(auth.KeystoneStrategy, '_do_request', fake_do_request)

        unauthorized_creds = [
            {
                'username': 'wronguser',
                'auth_url': 'http://localhost/badauthurl/',
                'strategy': 'keystone',
                'region': 'RegionOne',
                'password': 'pass'
            },  # wrong username
            {
                'username': 'user1',
                'auth_url': 'http://localhost/badauthurl/',
                'strategy': 'keystone',
                'region': 'RegionOne',
                'password': 'badpass'
            },  # bad password...
        ]

        for creds in unauthorized_creds:
            try:
                plugin = auth.KeystoneStrategy(creds)
                plugin.authenticate()
                self.fail("Failed to raise NotAuthenticated when supplying "
                          "bad credentials: %r" % creds)
            except exception.NotAuthenticated:
                continue  # Expected

        no_strategy_creds = {
                'username': 'user1',
                'auth_url': 'http://localhost/redirect/',
                'password': 'pass',
                'region': 'RegionOne'
        }

        try:
            plugin = auth.KeystoneStrategy(no_strategy_creds)
            plugin.authenticate()
            self.fail("Failed to raise MissingCredentialError when "
                      "supplying no strategy: %r" % no_strategy_creds)
        except exception.MissingCredentialError:
            pass  # Expected

        good_creds = [
            {
                'username': 'user1',
                'auth_url': 'http://localhost/redirect/',
                'password': 'pass',
                'strategy': 'keystone',
                'region': 'RegionOne'
            }
        ]

        for creds in good_creds:
            plugin = auth.KeystoneStrategy(creds)
            self.assertTrue(plugin.authenticate() is None)

    def test_v2_auth(self):
        """Test v2 auth code paths"""
        mock_token = None

        def fake_do_request(cls, url, method, headers=None, body=None):
            if (not url.rstrip('/').endswith('v2.0/tokens') or
                url.count("2.0") != 1):
                self.fail("Invalid v2.0 token path (%s)" % url)

            creds = json.loads(body)['auth']
            username = creds['passwordCredentials']['username']
            password = creds['passwordCredentials']['password']
            tenant = creds['tenantName']
            resp = webob.Response()

            if (username != 'user1' or password != 'pass' or
                tenant != 'tenant-ok'):
                resp.status = 401
            else:
                resp.status = 200
                body = mock_token.token

            return FakeResponse(resp), json.dumps(body)

        mock_token = V2Token()
        mock_token.add_service('image', ['RegionOne'])
        self.stubs.Set(auth.KeystoneStrategy, '_do_request', fake_do_request)

        unauthorized_creds = [
            {
                'username': 'wronguser',
                'auth_url': 'http://localhost/v2.0',
                'password': 'pass',
                'tenant': 'tenant-ok',
                'strategy': 'keystone',
                'region': 'RegionOne'
            },  # wrong username
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v2.0',
                'password': 'badpass',
                'tenant': 'tenant-ok',
                'strategy': 'keystone',
                'region': 'RegionOne'
            },  # bad password...
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v2.0',
                'password': 'pass',
                'tenant': 'carterhayes',
                'strategy': 'keystone',
                'region': 'RegionOne'
            },  # bad tenant...
        ]

        for creds in unauthorized_creds:
            try:
                plugin = auth.KeystoneStrategy(creds)
                plugin.authenticate()
                self.fail("Failed to raise NotAuthenticated when supplying "
                          "bad credentials: %r" % creds)
            except exception.NotAuthenticated:
                continue  # Expected

        no_region_creds = {
                'username': 'user1',
                'tenant': 'tenant-ok',
                'auth_url': 'http://localhost/redirect/v2.0/',
                'password': 'pass',
                'strategy': 'keystone'
        }

        plugin = auth.KeystoneStrategy(no_region_creds)
        self.assertTrue(plugin.authenticate() is None)
        self.assertEquals(plugin.management_url, 'http://localhost:9292')

        # Add another image service, with a different region
        mock_token.add_service('image', ['RegionTwo'])

        try:
            plugin = auth.KeystoneStrategy(no_region_creds)
            plugin.authenticate()
            self.fail("Failed to raise RegionAmbiguity when no region present "
                      "and multiple regions exist: %r" % no_region_creds)
        except exception.RegionAmbiguity:
            pass  # Expected

        wrong_region_creds = {
                'username': 'user1',
                'tenant': 'tenant-ok',
                'auth_url': 'http://localhost/redirect/v2.0/',
                'password': 'pass',
                'strategy': 'keystone',
                'region': 'NonExistantRegion'
        }

        try:
            plugin = auth.KeystoneStrategy(wrong_region_creds)
            plugin.authenticate()
            self.fail("Failed to raise NoServiceEndpoint when supplying "
                      "wrong region: %r" % wrong_region_creds)
        except exception.NoServiceEndpoint:
            pass  # Expected

        no_strategy_creds = {
                'username': 'user1',
                'tenant': 'tenant-ok',
                'auth_url': 'http://localhost/redirect/v2.0/',
                'password': 'pass',
                'region': 'RegionOne'
        }

        try:
            plugin = auth.KeystoneStrategy(no_strategy_creds)
            plugin.authenticate()
            self.fail("Failed to raise MissingCredentialError when "
                      "supplying no strategy: %r" % no_strategy_creds)
        except exception.MissingCredentialError:
            pass  # Expected

        bad_strategy_creds = {
            'username': 'user1',
            'tenant': 'tenant-ok',
            'auth_url': 'http://localhost/redirect/v2.0/',
            'password': 'pass',
            'region': 'RegionOne',
            'strategy': 'keypebble'
        }

        try:
            plugin = auth.KeystoneStrategy(bad_strategy_creds)
            plugin.authenticate()
            self.fail("Failed to raise BadAuthStrategy when supplying "
                      "bad auth strategy: %r" % bad_strategy_creds)
        except exception.BadAuthStrategy:
            pass  # Expected

        mock_token = V2Token()
        mock_token.add_service('image', ['RegionOne', 'RegionTwo'])

        good_creds = [
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v2.0/',
                'password': 'pass',
                'tenant': 'tenant-ok',
                'strategy': 'keystone',
                'region': 'RegionOne'
            },  # auth_url with trailing '/'
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v2.0',
                'password': 'pass',
                'tenant': 'tenant-ok',
                'strategy': 'keystone',
                'region': 'RegionOne'
            },   # auth_url without trailing '/'
            {
                'username': 'user1',
                'auth_url': 'http://localhost/v2.0',
                'password': 'pass',
                'tenant': 'tenant-ok',
                'strategy': 'keystone',
                'region': 'RegionTwo'
            }   # Second region
        ]

        for creds in good_creds:
            plugin = auth.KeystoneStrategy(creds)
            self.assertTrue(plugin.authenticate() is None)
            self.assertEquals(plugin.management_url, 'http://localhost:9292')

        ambiguous_region_creds = {
            'username': 'user1',
            'auth_url': 'http://localhost/v2.0/',
            'password': 'pass',
            'tenant': 'tenant-ok',
            'strategy': 'keystone',
            'region': 'RegionOne'
        }

        mock_token = V2Token()
        # Add two identical services
        mock_token.add_service('image', ['RegionOne'])
        mock_token.add_service('image', ['RegionOne'])

        try:
            plugin = auth.KeystoneStrategy(ambiguous_region_creds)
            plugin.authenticate()
            self.fail("Failed to raise RegionAmbiguity when "
                      "non-unique regions exist: %r" % ambiguous_region_creds)
        except exception.RegionAmbiguity:
            pass

        mock_token = V2Token()
        mock_token.add_service('bad-image', ['RegionOne'])

        good_creds = {
            'username': 'user1',
            'auth_url': 'http://localhost/v2.0/',
            'password': 'pass',
            'tenant': 'tenant-ok',
            'strategy': 'keystone',
            'region': 'RegionOne'
        }

        try:
            plugin = auth.KeystoneStrategy(good_creds)
            plugin.authenticate()
            self.fail("Failed to raise NoServiceEndpoint when bad service "
                      "type encountered")
        except exception.NoServiceEndpoint:
            pass

        mock_token = V2Token()
        mock_token.add_service_no_type()

        try:
            plugin = auth.KeystoneStrategy(good_creds)
            plugin.authenticate()
            self.fail("Failed to raise NoServiceEndpoint when bad service "
                      "type encountered")
        except exception.NoServiceEndpoint:
            pass
