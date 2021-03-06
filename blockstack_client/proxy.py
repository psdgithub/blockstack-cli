#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    Blockstack-client
    ~~~~~
    copyright: (c) 2014-2015 by Halfmoon Labs, Inc.
    copyright: (c) 2016 by Blockstack.org

    This file is part of Blockstack-client.

    Blockstack-client is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Blockstack-client is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.
    You should have received a copy of the GNU General Public License
    along with Blockstack-client. If not, see <http://www.gnu.org/licenses/>.
"""

import argparse
import sys
import json
import traceback
import types
import socket
import uuid
import os
import importlib
import pprint
import random
import time
import copy
import blockstack_profiles
import blockstack_zones
import urllib
from xmlrpclib import ServerProxy, Transport
from defusedxml import xmlrpc
import httplib
import base64
import jsonschema
from jsonschema.exceptions import ValidationError

# prevent the usual XML attacks
xmlrpc.MAX_DATA = 10 * 1024 * 1024      # 10MB
xmlrpc.monkey_patch()

import storage
import scripts

import pybitcoin
import bitcoin
import binascii
from utilitybelt import is_hex

import config
from config import get_logger, DEBUG, MAX_RPC_LEN, find_missing, BLOCKSTACKD_SERVER, \
    BLOCKSTACKD_PORT, BLOCKSTACK_METADATA_DIR, BLOCKSTACK_DEFAULT_STORAGE_DRIVERS, \
    FIRST_BLOCK_MAINNET, NAME_OPCODES, OPFIELDS, CONFIG_DIR, SPV_HEADERS_PATH, BLOCKCHAIN_ID_MAGIC, \
    NAME_PREORDER, NAME_REGISTRATION, NAME_UPDATE, NAME_TRANSFER, NAMESPACE_PREORDER, NAME_IMPORT, \
    USER_ZONEFILE_TTL, CONFIG_PATH, url_to_host_port, LENGTH_CONSENSUS_HASH, LENGTH_VALUE_HASH, \
    LENGTH_MAX_NAME, LENGTH_MAX_NAMESPACE_ID, TRANSFER_KEEP_DATA, TRANSFER_REMOVE_DATA, op_get_opcode_name

from .operations import SNV_CONSENSUS_EXTRA_METHODS, nameop_is_history_snapshot, \
                        nameop_history_extract, nameop_restore_from_history, \
                        nameop_snv_consensus_extra_quirks, nameop_snv_consensus_extra, \
                        nameop_restore_snv_consensus_fields

log = get_logger('blockstack-client')

OP_CONSENSUS_HASH_PATTERN = '^([0-9a-fA-F]{{{}}})$'.format(LENGTH_CONSENSUS_HASH*2)
OP_ADDRESS_PATTERN = '^([123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]+)$'
OP_P2PKH_PATTERN = '^76[aA]914[0-9a-fA-F]{40}88[aA][cC]$'
OP_SCRIPT_PATTERN = '^[0-9a-fA-F]+$'
OP_CODE_PATTERN = '^([{}]{{1}}|{}{}|{}{}|{}{})$'.format( ''.join([v for (k, v) in NAME_OPCODES.items()]), NAME_TRANSFER, TRANSFER_KEEP_DATA, NAME_TRANSFER, TRANSFER_REMOVE_DATA, NAME_REGISTRATION, NAME_REGISTRATION)
OP_CODE_NAME_PATTERN = '|'.join(k for (k, v) in NAME_OPCODES.items())
OP_PUBKEY_PATTERN = '^([0-9a-fA-F]+)$'
OP_SCRIPT_PATTERN = '^([0-9a-fA-F]+)$'
OP_TXID_PATTERN = '^([0-9a-fA-F]){64}$'
OP_ZONEFILE_HASH_PATTERN = '^([0-9a-fA-F]{{{}}})$'.format( LENGTH_VALUE_HASH * 2 )
OP_NAME_PATTERN = '^([a-z0-9\-_.+]{{{},{}}})$'.format( 3, LENGTH_MAX_NAME )
OP_NAMESPACE_PATTERN = '^([a-z0-9\-_+]{{{},{}}})$'.format( 1, LENGTH_MAX_NAMESPACE_ID )
OP_NAMESPACE_HASH_PATTERN = '^([0-9a-fA-F]{16})$'

OP_HISTORY_SCHEMA = {
    'type': 'object',
    'properties': {
        'address': {
            'type': 'string',
            'pattern': OP_ADDRESS_PATTERN,
        },
        'base': {
            'type': 'integer',
        },
        'buckets': {
            'anyOf': [
                {
                    'type': 'array',
                    'items': {
                        'type': 'integer',
                        'minItems': 16,
                        'maxItems': 16,
                    },
                },
                {
                    'type': 'null',
                },
            ],
        },
        'block_number': {
            'type': 'integer',
        },
        'coeff': {
            'anyOf': [
                {
                    'type': 'integer',
                },
                {
                    'type': 'null'
                },
            ],
        },
        'consensus_hash': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_CONSENSUS_HASH_PATTERN,
                },
                {
                    'type': 'null'
                },
            ],
        },
        'fee': {
            'type': 'integer',
        },
        'first_registered': {
            'type': 'integer',
        },
        'history_snapshot': {
            'type': 'boolean',
        },
        'importer': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_P2PKH_PATTERN,
                },
                {
                    'type': 'null',
                },
            ],
        },
        'importer_address': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_ADDRESS_PATTERN,
                },
                {
                    'type': 'null',
                },
            ],
        },
        'last_renewed': {
            'type': 'integer',
        },
        'op': {
            'type': 'string',
            'pattern': OP_CODE_PATTERN,
        },
        'op_fee': {
            'type': 'number',
        },
        'opcode': {
            'type': 'string',
            'pattern': OP_CODE_NAME_PATTERN,
        },
        'revoked': {
            'type': 'boolean',
        },
        'sender': {
            'type': 'string',
            'pattern': OP_SCRIPT_PATTERN,
        },
        'sender_pubkey': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_PUBKEY_PATTERN,
                },
                {
                    'type': 'null'
                },
            ],
        },
        'recipient': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_SCRIPT_PATTERN,
                },
                {
                    'type': 'null'
                },
            ],
        },
        'recipient_address': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_ADDRESS_PATTERN,
                },
                {
                    'type': 'null'
                },
            ],
        },
        'recipient_pubkey': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_PUBKEY_PATTERN,
                },
                {
                    'type': 'null'
                },
            ],
        },
        'txid': {
            'type': 'string',
            'pattern': OP_TXID_PATTERN,
        },
        'value_hash': {
            'anyOf': [
                {
                    'type': 'string',
                    'pattern': OP_ZONEFILE_HASH_PATTERN,
                },
                {
                    'type': 'null',
                },
            ],
        },
        'vtxindex': {
            'type': 'integer',
        },
    },
    'required': [
        'op',
        'opcode',
        'txid',
        'vtxindex'
    ],
}

NAMEOP_SCHEMA_PROPERTIES = {
    'address': OP_HISTORY_SCHEMA['properties']['address'],
    'block_number': OP_HISTORY_SCHEMA['properties']['block_number'],
    'consensus_hash': OP_HISTORY_SCHEMA['properties']['consensus_hash'],
    'expire_block': {
        'type': 'integer',
    },
    'first_registered': OP_HISTORY_SCHEMA['properties']['first_registered'],
    'history': {
        'type': 'object',
        'patternProperties': {
            '^([0-9]+)$': {
                'type': 'array',
                'items': OP_HISTORY_SCHEMA,
            },
        },
    },
    'history_snapshot': {
        'type': 'boolean',
    },
    'importer': OP_HISTORY_SCHEMA['properties']['importer'],
    'importer_address': OP_HISTORY_SCHEMA['properties']['importer_address'],
    'last_renewed': OP_HISTORY_SCHEMA['properties']['last_renewed'],
    'name': {
        'type': 'string',
        'pattern': OP_NAME_PATTERN,
    },
    'op': OP_HISTORY_SCHEMA['properties']['op'],
    'op_fee': OP_HISTORY_SCHEMA['properties']['op_fee'],
    'opcode': OP_HISTORY_SCHEMA['properties']['opcode'],
    'revoked': OP_HISTORY_SCHEMA['properties']['revoked'],
    'sender': OP_HISTORY_SCHEMA['properties']['sender'],
    'sender_pubkey': OP_HISTORY_SCHEMA['properties']['sender_pubkey'],
    'recipient': OP_HISTORY_SCHEMA['properties']['recipient'],
    'recipient_address': OP_HISTORY_SCHEMA['properties']['recipient_address'],
    'txid': OP_HISTORY_SCHEMA['properties']['txid'],
    'value_hash': OP_HISTORY_SCHEMA['properties']['value_hash'],
    'vtxindex': OP_HISTORY_SCHEMA['properties']['vtxindex'],
}

NAMESPACE_SCHEMA_PROPERTIES = {
    'address': OP_HISTORY_SCHEMA['properties']['address'],
    'base': OP_HISTORY_SCHEMA['properties']['base'],
    'block_number': OP_HISTORY_SCHEMA['properties']['block_number'],
    'buckets': OP_HISTORY_SCHEMA['properties']['buckets'],
    'coeff': OP_HISTORY_SCHEMA['properties']['coeff'],
    'fee': OP_HISTORY_SCHEMA['properties']['fee'],
    'history': {
        'type': 'object',
        'patternProperties': {
            '^([0-9]+)$': {
                'type': 'array',
                'items': OP_HISTORY_SCHEMA,
            },
        },
    },
    'lifetime': {
        'type': 'integer'
    },
    'namespace_id': {
        'type': 'string',
        'pattern': OP_NAMESPACE_PATTERN,
    },
    'namespace_id_hash': {
        'type': 'string',
        'pattern': OP_NAMESPACE_HASH_PATTERN,
    },
    'no_vowel_discount': {
        'type': 'integer',
    },
    'nonalpha_discount': {
        'type': 'integer',
    },
    'op': OP_HISTORY_SCHEMA['properties']['op'],
    'ready': {
        'type': 'boolean',
    },
    'ready_block': {
        'type': 'integer',
    },
    'recipient': OP_HISTORY_SCHEMA['properties']['recipient'],
    'recipient_address': OP_HISTORY_SCHEMA['properties']['recipient_address'],
    'reveal_block': {
        'type': 'integer',
    },
    'sender': OP_HISTORY_SCHEMA['properties']['sender'],
    'sender_pubkey': OP_HISTORY_SCHEMA['properties']['sender_pubkey'],
    'txid': OP_HISTORY_SCHEMA['properties']['txid'],
    'version': {
        'type': 'integer',
    },
    'vtxindex': OP_HISTORY_SCHEMA['properties']['vtxindex'],
}

NAMEOP_SCHEMA_REQUIRED = [
    'address',
    'block_number',
    'op',
    'op_fee',
    'opcode',
    'sender',
    'txid',
    'vtxindex'
]

NAMESPACE_SCHEMA_REQUIRED = [
    'address',
    'base',
    'block_number',
    'buckets',
    'coeff',
    'lifetime',
    'namespace_id',
    'no_vowel_discount',
    'nonalpha_discount',
    'op',
    'ready',
    'recipient',
    'recipient_address',
    'reveal_block',
    'sender',
    'sender_pubkey',
    'txid',
    'version',
    'vtxindex'
]

# borrowed with gratitude from Justin Cappos
# https://seattle.poly.edu/browser/seattle/trunk/demokit/timeout_xmlrpclib.py?rev=692
class TimeoutHTTPConnection(httplib.HTTPConnection):
    def connect(self):
        httplib.HTTPConnection.connect(self)
        self.sock.settimeout(self.timeout)


class TimeoutHTTP(httplib.HTTP):
    _connection_class = TimeoutHTTPConnection

    def set_timeout(self, timeout):
        self._conn.timeout = timeout

    def getresponse(self, **kw):
        return self._conn.getresponse(**kw)


class TimeoutTransport(Transport):
    def __init__(self, *l, **kw):
        self.timeout = kw.get('timeout', 10)
        if 'timeout' in kw.keys():
            del kw['timeout']

        Transport.__init__(self, *l, **kw)

    def make_connection(self, host):
        conn = TimeoutHTTP(host)
        conn.set_timeout(self.timeout)
        return conn

class TimeoutServerProxy(ServerProxy):
    def __init__(self, uri, *l, **kw):
        kw['transport'] = TimeoutTransport(timeout=kw.get('timeout',10), use_datetime=kw.get('use_datetime', 0))
        if 'timeout' in kw.keys():
            del kw['timeout']
        
        ServerProxy.__init__(self, uri, *l, **kw)


# default API endpoint proxy to blockstackd
default_proxy = None

class BlockstackRPCClient(object):
    """
    RPC client for the blockstack server
    """
    def __init__(self, server, port, max_rpc_len=MAX_RPC_LEN, timeout=config.DEFAULT_TIMEOUT, debug_timeline=False, **kw ):
        self.srv = TimeoutServerProxy( 'http://%s:%s' % (server, port), timeout=timeout, allow_none=True )
        self.server = server
        self.port = port
        self.debug_timeline = debug_timeline

    def __getattr__(self, key):
        try:
            return object.__getattr__(self, key)
        except AttributeError, ae:

            # random ID to match in logs
            if self.debug_timeline:
                r = random.randint(0, 2**16)
                log.debug('RPC(%s) begin http://%s:%s %s' % (r, self.server, self.port, key))

            def inner(*args, **kw):
                func = getattr(self.srv, key)
                res = func(*args, **kw)
                if res is not None:
                    # lol jsonrpc within xmlrpc
                    try:
                        res = json.loads(res)
                    except (ValueError, TypeError):
                        if os.environ.get('BLOCKSTACK_TEST') == '1':
                            log.debug('Server replied invalid JSON: %s' % res)

                        log.error('Server replied invalid JSON')
                        res = {'error': 'Server replied invalid JSON'}

                if self.debug_timeline:
                    log.debug('RPC(%s) end http://%s:%s %s' % (r, self.server, self.port, key))

                return res

            return inner


def get_default_proxy(config_path=CONFIG_PATH):
    """
    Get the default API proxy to blockstack.
    """
    global default_proxy
    if default_proxy is None:

        import client

        if os.environ.get('BLOCKSTACK_CLIENT_TEST_ALTERNATIVE_CONFIG', None) == '1':
            # feature test: make sure alternative config paths get propagated
            if config_path.startswith('/home'):
                print config_path
                traceback.print_stack()
                os.abort()

        # load     
        conf = config.get_config(config_path)
        assert conf is not None, 'Failed to get config from "{}"'.format(config_path)
        blockstack_server = conf['server']
        blockstack_port = conf['port']

        log.debug('Default proxy to %s:%s' % (blockstack_server, blockstack_port))
        proxy = client.session(conf=conf, server_host=blockstack_server, server_port=blockstack_port)

        return proxy

    else:
        return default_proxy


def set_default_proxy(proxy):
    """
    Set the default API proxy
    """
    global default_proxy
    default_proxy = proxy


def json_is_error( resp ):
    """
    Is the given response object
    (be it a string, int, or dict)
    an error message?

    Return True if so
    Return False if not
    """

    if not isinstance(resp, dict):
        return False

    return 'error' in resp


def json_validate( schema, resp ):
    """
    Validate an RPC response.
    The response must either take the
    form of the given schema, or it must
    take the form of {'error': ...}

    Returns the resp on success
    Returns {'error': ...} on validation error
    """
    error_schema = {
        'type': 'object',
        'properties': {
            'error': {
                'type': 'string'
            }
        },
        'required': [
            'error'
        ]
    }

    # is this an error?
    try:
        jsonschema.validate(resp, error_schema)
    except ValidationError:
        # not an error.
        jsonschema.validate(resp, schema)

    return resp
   

def json_traceback( error_msg=None ):
    """
    Generate a stack trace as a JSON-formatted error message.
    Optionally use error_msg as the error field.
    Return {'error': ..., 'traceback'...}
    """

    exception_data = traceback.format_exc().splitlines()
    if error_msg is None:
        error_msg = exception_data[-1]
    
    else:
        error_msg = 'Remote RPC error: {}'.format(error_msg)

    return {
        'error': error_msg,
        'traceback': exception_data
    }


def json_response_schema( expected_object_schema ):
    """
    Make a schema for a "standard" server response.
    Standard server responses have 'status': True
    and possibly 'indexing': True set.
    """
    schema = {
        'type': 'object',
        'properties': {
            'status': {
                'type': 'boolean',
            },
            'indexing': {
                'type': 'boolean',
            },
            'lastblock': {
                'anyOf': [
                    {
                        'type': 'integer',
                    },
                    {
                        'type': 'null',
                    },
                ],
            },
        },
        'required': [
            'status',
            'indexing',
            'lastblock'
        ],
    }

    # fold in the given object schema 
    schema['properties'].update( expected_object_schema['properties'] )
    schema['required'] = list(set( schema['required'] + expected_object_schema['required'] ))

    return schema



def getinfo(proxy=None):
    """
    getinfo
    Returns server info on success
    Returns {'error': ...} on error
    """

    schema = {
        'type': 'object',
        'properties': {
            'last_block_seen': {
                'type': 'integer'
            },
            'consensus': {
                'type': 'string'
            },
            'server_version': {
                'type': 'string'
            },
            'last_block_processed': {
                'type': 'integer'
            },
            'server_alive': {
                'type': 'boolean'
            },
            'zonefile_count': {
                'type': 'integer'
            },
            'indexing': {
                'type': 'boolean'
            }
        },
        'required': [
            'last_block_seen',
            'consensus',
            'server_version',
            'last_block_processed',
            'server_alive',
            'indexing'
        ]
    }

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.getinfo()
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))

    return resp


def ping(proxy=None):
    """
    ping
    Returns {'alive': True} on succcess
    Returns {'error': ...} on error
    """

    schema = {
        'type': 'object',
        'properties': {
            'status': {
                'type': 'string'
            },
        },
        'required': [
            'status'
        ]
    }


    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.ping()
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

        assert resp['status'] == 'alive'

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))

    return resp


def get_name_cost(name, proxy=None):
    """
    name_cost
    Returns the name cost info on success
    Returns {'error': ...} on error
    """

    schema = {
        'type': 'object',
        'properties': {
            'status': {
                'type': 'boolean',
            },
            'satoshis': {
                'type': 'integer',
            },
        },
        'required': [
            'status',
            'satoshis'
        ]
    }

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_name_cost(name)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        resp = json_traceback(resp.get('error'))

    return resp


def get_namespace_cost(namespace_id, proxy=None):
    """
    namespace_cost
    Returns the namespace cost info on success
    Returns {'error': ...} on error
    """

    cost_schema = {
        'type': 'object',
        'properties': {
            'satoshis': {
                'type': 'integer',
            }
        },
        'required': [
            'satoshis'
        ]
    }

    schema = json_response_schema( cost_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_namespace_cost(namespace_id)
        resp = json_validate( cost_schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        resp = json_traceback(resp.get('error'))

    return resp


def get_all_names_page(offset, count, proxy=None):
    """
    get a page of all the names
    Returns the list of names on success
    Returns {'error': ...} on error
    """

    page_schema = {
        'type': 'object',
        'properties': {
            'names': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'uniqueItems': True
                },
            },
        },
        'required': [
            'names',
        ],
    }

    schema = json_response_schema( page_schema )

    assert count <= 100, "Page too big: %s" % count

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_all_names(offset, count)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

        # must be valid names
        for n in resp['names']:
            assert scripts.is_name_valid(str(n)), ("Invalid name '%s'" % str(n))

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['names']


def get_num_names( proxy=None ):
    """
    Get the number of names
    Return {'error': ...} on failure
    """

    schema = {
        'type': 'object',
        'properties': {
            'count': {
                'type': 'integer',
            },
        },
        'required': [
            'count',
        ],
    }

    count_schema = json_response_schema( schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_num_names()
        resp = json_validate( count_schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['count']


def get_all_names( offset=None, count=None, proxy=None ):
    """
    Get all names within the given range.
    Return the list of names on success
    Return {'error': ...} on failure
    """
    offset = 0 if offset is None else offset
    proxy = get_default_proxy() if proxy is None else proxy

    if count is None:
        # get all names after this offset
        count = get_num_names( proxy=proxy )
        if json_is_error(count):
            # error
            return count

        count -= offset

    page_size = 100
    all_names = []
    while len(all_names) < count:
        request_size = page_size
        if count - len(all_names) < request_size:
            request_size = count - len(all_names)

        page = get_all_names_page( offset + len(all_names), request_size, proxy=proxy )
        if json_is_error(page):
            # error
            return page

        if len(page) > request_size:
            # error
            error_str = 'server replied too much data'
            return {'error': error_str}

        all_names += page

    return all_names


def get_names_in_namespace_page(namespace_id, offset, count, proxy=None):
    """
    Get a page of names in a namespace
    Returns the list of names on success
    Returns {'error': ...} on error
    """

    names_schema = {
        'type': 'object',
        'properties': {
            'names': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'uniqueItems': True
                },
            },
        },
        'required': [
            'names',
        ],
    }

    schema = json_response_schema( names_schema )

    assert count <= 100, "Page too big: %s" % count

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_names_in_namespace(namespace_id, offset, count)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

        # must be valid names
        for n in resp['names']:
            assert scripts.is_name_valid(str(n)), ("Invalid name %s" % str(n))

    except (ValidationError, AssertionError) as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['names']


def get_num_names_in_namespace( namespace_id, proxy=None ):
    """
    Get the number of names in a namespace
    Returns the count on success
    Returns {'error': ...} on error
    """

    num_names_schema = {
        'type': 'object',
        'properties': {
            'count': {
                'type': 'integer'
            },
        },
        'required': [
            'count',
        ],
    }

    schema = json_response_schema( num_names_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_num_names_in_namespace( namespace_id )
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['count']


def get_names_in_namespace( namespace_id, offset=None, count=None, proxy=None ):
    """
    Get all names in a namespace
    Returns the list of names on success
    Returns {'error': ..} on error
    """
    offset = 0 if offset is None else offset
    if count is None:
        # get all names in this namespace after this offset
        count = get_num_names_in_namespace(namespace_id, proxy=proxy)
        if json_is_error(count):
            return count

        count -= offset

    page_size = 100
    all_names = []
    while len(all_names) < count:
        request_size = page_size
        if count - len(all_names) < request_size:
            request_size = count - len(all_names)

        page = get_names_in_namespace_page( namespace_id, offset + len(all_names), request_size, proxy=proxy )
        if json_is_error(page):
            # error
            return page

        if len(page) > request_size:
            # error
            error_str = 'server replied too much data'
            return {'error': error_str}

        all_names += page

    return all_names[:count]


def get_names_owned_by_address(address, proxy=None):
    """
    Get the names owned by an address.
    Returns the list of names on success
    Returns {'error': ...} on error
    """

    owned_schema = {
        'type': 'object',
        'properties': {
            'names': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'uniqueItems': True
                },
            },
        },
        'required': [
            'names',
        ],
    }

    schema = json_response_schema( owned_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_names_owned_by_address(address)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp
        
        # names must be valid 
        for n in resp['names']:
            assert scripts.is_name_valid(str(n)), ("Invalid name '%s'" % str(n))

    except (ValidationError, AssertionError) as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['names']


def get_consensus_at(block_height, proxy=None):
    """
    Get consensus at a block
    Returns the consensus hash on success
    Returns {'error': ...} on error
    """
    consensus_schema = {
        'type': 'object',
        'properties': {
            'consensus': {
                'type': 'string',
                'pattern': OP_CONSENSUS_HASH_PATTERN,
            },
        },
        'required': [
            'consensus',
        ],
    }

    resp_schema = json_response_schema( consensus_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_consensus_at(block_height)
        resp = json_validate( resp_schema, resp )
        if json_is_error(resp):
            return resp

    except (ValidationError, AssertionError) as e:
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['consensus']


def get_consensus_hashes(block_heights, proxy=None):
    """
    Get consensus hashes for a list of blocks
    NOTE: returns {block_height (int): consensus_hash (str)}
    (coerces the key to an int)
    Returns {'error': ...} on error
    """

    consensus_hashes_schema = {
        'type': 'object',
        'properties': {
            'consensus_hashes': {
                'type': 'object',
                'patternProperties': {
                    '^([0-9]+)$': {
                        'type': 'string',
                        'pattern': OP_CONSENSUS_HASH_PATTERN,
                    },
                },
            },
        },
        'required': [
            'consensus_hashes',
        ],
    }

    resp_schema = json_response_schema( consensus_hashes_schema )
    
    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_consensus_hashes(block_heights)
        resp = json_validate( resp_schema, resp )
        if json_is_error(resp):
            log.error("Failed to get consensus hashes for %s: %s" % (block_heights, resp['error']))
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    consensus_hashes = resp['consensus_hashes']

    # hard to express as a JSON schema, but the format is thus:
    # { block_height (str): consensus_hash (str) }
    # need to convert all block heights to ints
    ret = {}
    for h in consensus_hashes.keys():
        try:
            hint = int(h)
            ret[hint] = consensus_hashes[h]
        except:
            return {'error': 'Invalid data: expected int'}
       
    log.debug("consensus hashes: %s" % ret)
    return ret


def get_consensus_range(block_id_start, block_id_end, proxy=None):
    """
    Get a range of consensus hashes.  The range is inclusive.
    """
    ch_range = get_consensus_hashes( range(block_id_start, block_id_end+1), proxy=proxy )
    if 'error' in ch_range:
        return ch_range

    # verify that all blocks are included 
    for i in range(block_id_start, block_id_end+1):
        if i not in ch_range.keys():
            return {'error': 'Missing consensus hashes'}

    return ch_range


def get_block_from_consensus(consensus_hash, proxy=None):
    """
    Get a block ID from a consensus hash
    """
    consensus_schema = {
        'type': 'object',
        'properties': {
            'block_id': {
                'anyOf': [
                    {
                        'type': 'integer',
                    },
                    {
                        'type': 'null',
                    },
                ],
            },
        },
        'required': [
            'block_id'
        ],
    }

    schema = json_response_schema( consensus_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_block_from_consensus(consensus_hash)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            log.error("Failed to find block ID for %s" % consensus_hash)
            return resp

    except ValidationError as ve:
        log.exception(ve)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['block_id']


def get_name_history_blocks( name, proxy=None ):
    """
    Get the list of blocks at which this name was affected.
    Returns the list of blocks on success
    Returns {'error': ...} on error
    """
    hist_schema = {
        'type': 'array',
        'items': {
            'type': 'integer',
        },
    }

    hist_list_schema = {
        'type': 'object',
        'properties': {
            'history_blocks': hist_schema
        },
        'required': [
            'history_blocks'
        ],
    }

    resp_schema = json_response_schema( hist_list_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_name_history_blocks( name )
        resp = json_validate( resp_schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['history_blocks']


def get_name_at( name, block_id, proxy=None ):
    """
    Get the name as it was at a particular height.
    Returns the name record states on success (an array)
    Returns {'error': ...} on error
    """
    namerec_schema = {
        'type': 'object',
        'properties': NAMEOP_SCHEMA_PROPERTIES,
        'required': NAMEOP_SCHEMA_REQUIRED
    }

    namerec_list_schema = {
        'type': 'object',
        'properties': {
            'records': {
                'type': 'array',
                'items': namerec_schema
            },
        },
        'required': [
            'records'
        ],
    }

    resp_schema = json_response_schema( namerec_list_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_name_at( name, block_id )
        resp = json_validate( resp_schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['records']


def get_name_blockchain_history(name, start_block, end_block, proxy=None):
    """
    Get the name's historical blockchain records.
    Returns the list of states the name has been in on success, as a dict,
    mapping {block_id: [states]}

    Returns {'error': ...} on error
    """
    if proxy is None:
        proxy = get_default_proxy()

    history_blocks = get_name_history_blocks( name, proxy=proxy )
    if json_is_error(history_blocks):
        # error
        return history_blocks

    query_blocks = filter( lambda b: b >= start_block and b <= end_block, history_blocks )
    query_blocks.sort()
    ret = {}

    for qb in query_blocks:
        name_at = get_name_at( name, qb )
        if json_is_error(name_at):
            # error
            return name_at

        ret[qb] = name_at

    return ret


def get_op_history_rows( name, proxy=None ):
    """
    Get the history rows for a name or namespace.
    """
    history_schema = {
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'txid': {
                    'type': 'string',
                    'pattern': OP_TXID_PATTERN,
                },
                'history_id': {
                    'type': 'string',
                    'pattern': '^({})$'.format(name),
                },
                'block_id': {
                    'type': 'integer',
                },
                'vtxindex': {
                    'type': 'integer',
                },
                'op': {
                    'type': 'string',
                    'pattern': OP_CODE_PATTERN,
                },
                'history_data': {
                    'type': 'string'
                },
            },
            'required': [
                'txid',
                'history_id',
                'block_id',
                'vtxindex',
                'op',
                'history_data',
            ],
        },
    }

    hist_count_schema = {
        'type': 'object',
        'properties': {
            'count': {
                'type': 'integer'
            },
        },
        'required': [
            'count'
        ],
    }

    hist_rows_schema = {
        'type': 'object',
        'properties': {
            'history_rows': history_schema
        },
        'required': [
            'history_rows'
        ]
    }

    count_schema = json_response_schema( hist_count_schema )
    resp_schema = json_response_schema( hist_rows_schema )

    if proxy is None:
        proxy = get_default_proxy()

    # how many history rows?
    history_rows_count = None
    try:
        history_rows_count = proxy.get_num_op_history_rows(name)
        history_rows_count = json_validate( count_schema, history_rows_count )
        if json_is_error(history_rows_count):
            return history_rows_count

    except ValidationError as e:
        resp = json_traceback()
        return resp

    history_rows = []
    history_rows_count = history_rows_count['count']
    page_size = 10
    while len(history_rows) < history_rows_count:
        resp = {}
        try:
            resp = proxy.get_op_history_rows(name, len(history_rows), page_size)
            resp = json_validate( resp_schema, resp )
            if json_is_error(resp):
                return resp

            history_rows += resp['history_rows']
        
            if os.environ.get("BLOCKSTACK_TEST", None) == "1":
                if len(resp['history_rows']) != page_size:
                    if len(history_rows) != history_rows_count:
                        # something's wrong--we should have them all 
                        raise Exception('Missing history rows: expected %s, got %s' % (history_rows_count, len(history_rows)))

        except ValidationError as e:
            log.exception(e)
            resp = json_traceback(resp.get('error'))
            return resp

    return history_rows


def get_nameops_affected_at( block_id, proxy=None ):
    """
    Get the *current* states of the name records that were
    affected at the given block height.
    Return the list of name records at the given height on success.
    Return {'error': ...} on error.
    """

    history_schema = {
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': OP_HISTORY_SCHEMA['properties'],
            'required': [
                'op',
                'opcode',
                'txid',
                'vtxindex',
            ]
        }
    }

    nameop_history_schema = {
        'type': 'object',
        'properties': {
            'nameops': history_schema,
        },
        'required': [
            'nameops',
        ],
    }

    history_count_schema = {
        'type': 'object',
        'properties': {
            'count': {
                'type': 'integer'
            },
        },
        'required': [
            'count',
        ],
    }
    
    count_schema = json_response_schema( history_count_schema )
    nameop_schema = json_response_schema( nameop_history_schema )

    if proxy is None:
        proxy = get_default_proxy()

    # how many nameops?
    num_nameops = None
    try:
        num_nameops = proxy.get_num_nameops_affected_at(block_id)
        num_nameops = json_validate( count_schema, num_nameops )
        if json_is_error(num_nameops):
            return num_nameops

    except ValidationError as e:
        num_nameops = json_traceback()
        return num_nameops

    num_nameops = num_nameops['count']

    # grab at most 10 of these at a time
    all_nameops = []
    page_size = 10
    while len(all_nameops) < num_nameops:
        resp = {}
        try:
            resp = proxy.get_nameops_affected_at(block_id, len(all_nameops), page_size)
            resp = json_validate( nameop_schema, resp )
            if json_is_error(resp):
                return resp

            all_nameops += resp['nameops']

            if os.environ.get("BLOCKSTACK_TEST", None) == "1":
                if len(resp['nameops']) != page_size:
                    if len(all_nameops) != num_nameops:
                        # something's wrong--we should have them all 
                        raise Exception('Missing nameops: expected %s, got %s' % (num_nameops, len(all_nameops)))
            
        except ValidationError as e:
            log.exception(e)
            resp = json_traceback(resp.get('error'))
            return resp

    return all_nameops


def get_nameops_at( block_id, proxy=None ):
    """
    Get all the name operation that happened at a given block,
    as they were written.
    Return the list of operations on success, ordered by transaction index.
    Return {'error': ...} on error.
    """

    all_nameops = get_nameops_affected_at( block_id, proxy=proxy )
    if json_is_error(all_nameops):
        log.debug("Failed to get nameops affected at %s: %s" % (block_id, all_nameops['error']))
        return all_nameops

    log.debug("%s nameops at %s" % (len(all_nameops), block_id))

    # get the history for each nameop 
    nameops = []
    nameop_histories = {}   # cache histories
    for nameop in all_nameops:
        # get history (if not a preorder)
        history_rows = []
        if nameop.has_key('name'):
            # If the nameop has a 'name' field, then it's not an outstanding preorder.
            # Outstanding preorders have no history, so we don't need to worry about 
            # getting history for them.
            history_rows = nameop_histories.get(nameop['name'])
            if history_rows is None:
                history_rows = get_op_history_rows( nameop['name'], proxy=proxy )
                if json_is_error(history_rows):
                    return history_rows

                nameop_histories[nameop['name']] = history_rows

        # restore history
        history = nameop_history_extract( history_rows )
        historic_nameops = nameop_restore_from_history( nameop, history, block_id )

        log.debug("%s had %s operations (%s history rows, %s historic nameops, txids: %s) at %s" % 
                (nameop.get('name', "UNKNOWN"), len(history.get(block_id, [])), len(history_rows), len(historic_nameops), [op['txid'] for op in historic_nameops], block_id))

        for historic_nameop in historic_nameops:
            # restore SNV consensus information
            historic_nameop['history'] = history
            restored_rec = nameop_restore_snv_consensus_fields( historic_nameop, block_id )
            if json_is_error(restored_rec):
                return restored_rec

            nameops.append(restored_rec)

    log.debug("restored %s nameops at height %s" % (len(nameops), block_id))
    return sorted(nameops, key=lambda n: n['vtxindex'])


def get_nameops_hash_at(block_id, proxy=None):
    """
    Get the hash of a set of records as they were at a particular block.
    Return the hash on success.
    Return {'error': ...} on error.
    """

    hash_schema = {
        'type': 'object',
        'properties': {
            'ops_hash': {
                'type': 'string',
                'pattern': '^([0-9a-fA-F]+)$'
            },
        },
        'required': [
            'ops_hash',
        ],
    }

    schema = json_response_schema( hash_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_nameops_hash_at(block_id)
        resp = json_validate( schema, resp )
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['ops_hash']


def get_name_blockchain_record(name, proxy=None):
    """
    get_name_blockchain_record
    Return the blockchain-extracted information on success.
    Return {'error': ...} on error
    """

    nameop_schema = {
        'type': 'object',
        'properties': NAMEOP_SCHEMA_PROPERTIES,
        'required': NAMEOP_SCHEMA_REQUIRED + ['history']
    }

    rec_schema = {
        'type': 'object',
        'properties': {
            'record': nameop_schema,
        },
        'required': [
            'record'
        ],
    }

    resp_schema = json_response_schema( rec_schema )

    if proxy is None:
        proxy = get_default_proxy()

    resp = {}
    try:
        resp = proxy.get_name_blockchain_record(name)
        resp = json_validate(resp_schema, resp)
        if json_is_error(resp):
            return resp

    except ValidationError as e:
        log.exception(e)
        resp = json_traceback(resp.get('error'))
        return resp

    return resp['record']


def get_namespace_blockchain_record(namespace_id, proxy=None):
    """
    get_namespace_blockchain_record
    """

    namespace_schema = {
        'type': 'object',
        'properties': NAMESPACE_SCHEMA_PROPERTIES,
        'required': NAMESPACE_SCHEMA_REQUIRED
    }

    rec_schema = {
        'type': 'object',
        'properties': {
            'record': namespace_schema,
        },
        'required': [
            'record',
        ],
    }

    resp_schema = json_response_schema( rec_schema )
            
    if proxy is None:
        proxy = get_default_proxy()

    ret = {}
    try:
        ret = proxy.get_namespace_blockchain_record(namespace_id)
        ret = json_validate(resp_schema, ret)
        if json_is_error(ret):
            return ret

        # this isn't needed
        if 'opcode' in ret['record']:
            del ret['record']['opcode']

    except ValidationError as e:
        log.exception(e)
        ret = json_traceback(ret.get('error'))
        return ret

    return ret['record']


def is_name_registered(fqu, proxy=None):
    """
    Return True if @fqu registered on blockchain
    """

    if proxy is None:
        proxy = get_default_proxy()

    blockchain_record = get_name_blockchain_record( fqu, proxy=proxy )
    if 'error' in blockchain_record:
        log.debug('Failed to read blockchain record for %s' % fqu)
        return False

    if blockchain_record.has_key('revoked') and blockchain_record['revoked']:
        return False

    if 'first_registered' in blockchain_record:
        return True
    else:
        return False


def has_zonefile_hash(fqu, proxy=None ):
    """
    Return True if @fqu has a zonefile hash on the blockchain
    """
    
    if proxy is None:
        proxy = get_default_proxy()

    blockchain_record = get_name_blockchain_record(fqu, proxy=proxy )
    if 'error' in blockchain_record:
        log.debug('Failed to read blockchain record for %s' % fqu)
        return False

    if 'value_hash' in blockchain_record and blockchain_record['value_hash'] is not None:
        return True
    else:
        return False


def is_zonefile_current(fqu, zonefile_json, proxy=None):
    """ 
    Return True if hash(@zonefile_json) published on blockchain
    """

    if proxy is None:
        proxy = get_default_proxy()

    zonefile_hash = storage.hash_zonefile(zonefile_json)
    return is_zonefile_hash_current( fqu, zonefile_hash, proxy=proxy )


def is_zonefile_hash_current(fqu, zonefile_hash, proxy=None):
    """ 
    Return True if hash(@zonefile_json) published on blockchain
    """

    if proxy is None:
        proxy = get_default_proxy()

    blockchain_record = get_name_blockchain_record( fqu, proxy=proxy )
    if 'error' in blockchain_record:
        log.debug('Failed to read blockchain record for %s' % fqu)
        return False

    if 'value_hash' in blockchain_record and blockchain_record['value_hash'] == zonefile_hash:
        # if hash of profile is in correct
        return True

    return False


def is_name_owner(fqu, address, proxy=None):
    """
    return True if @btc_address owns @fqu
    """

    if proxy is None:
        proxy = get_default_proxy()

    blockchain_record = get_name_blockchain_record( fqu, proxy=proxy )
    if 'error' in blockchain_record:
        log.debug('Failed to read blockchain record for %s' % fqu)
        return False

    if 'address' in blockchain_record and blockchain_record['address'] == address:
        return True
    else:
        return False


def get_zonefile_inventory( hostport, bit_offset, bit_count, timeout=30, my_hostport=None, proxy=None ):
    """
    Get the atlas zonefile inventory from the given peer.
    Return {'status': True, 'inv': inventory} on success.
    Return {'error': ...} on error
    """

    # NOTE: we want to match the empty string too
    base64_pattern = '^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$'

    inv_schema = {
        'type': 'object',
        'properties': {
            'inv': {
                'type': 'string',
                'pattern': base64_pattern,
            },
        },
        'required': [
            'inv'
        ]
    }

    schema = json_response_schema( inv_schema )

    if proxy is None:
        host, port = url_to_host_port( hostport )
        assert host is not None and port is not None
        proxy = BlockstackRPCClient( host, port, timeout=timeout, src=my_hostport )

    zf_inv = None
    try:
        zf_inv = proxy.get_zonefile_inventory( bit_offset, bit_count )
        zf_inv = json_validate( schema, zf_inv )
        if json_is_error(zf_inv):
            return zf_inv
        
        # decode
        zf_inv['inv'] = base64.b64decode( str(zf_inv['inv']) )
        
        # make sure it corresponds to this range
        assert len(zf_inv['inv']) <= (bit_count / 8) + (bit_count % 8), 'Zonefile inventory in is too long (got {} bytes)'.format(len(zf_inv['inv']))
    except (ValidationError, AssertionError) as e:
        log.exception(e)
        zf_inv = {'error': 'Failed to fetch and parse zonefile inventory'}

    return zf_inv
    

def get_atlas_peers( hostport, timeout=30, my_hostport=None, proxy=None ):
    """
    Get an atlas peer's neighbors.
    Return {'status': True, 'peers': [peers]} on success.
    Return {'error': ...} on error
    """

    peers_schema = {
        'type': 'object',
        'properties': {
            'peers': {
                'type': 'array',
                'items': {
                    'type': 'string',
                    'pattern': '^([^:]+):([1-9][0-9]{1,4})$',
                },
            },
        },
        'required': [
            'peers'
        ],
    }

    schema = json_response_schema( peers_schema )

    if proxy is None:
        host, port = url_to_host_port( hostport )
        assert host is not None and port is not None
        proxy = BlockstackRPCClient( host, port, timeout=timeout, src=my_hostport )

    peers = None
    try:
        peer_list_resp = proxy.get_atlas_peers()
        peer_list_resp = json_validate( schema, peer_list_resp )
        if json_is_error( peer_list_resp ):
            return peer_list_resp

        # verify that all strings are host:ports
        for peer_hostport in peer_list_resp['peers']:
            peer_host, peer_port = url_to_host_port( peer_hostport )
            if peer_host is None or peer_port is None:
                return {'error': 'Invalid peer listing'}

        peers = peer_list_resp
    except (ValidationError, AssertionError) as e:
        log.exception(e)
        peers = json_traceback()

    return peers


def get_zonefiles( hostport, zonefile_hashes, timeout=30, my_hostport=None, proxy=None ):
    """
    Get a set of zonefiles from the given server.
    Return {'status': True, 'zonefiles': {hash: data, ...}} on success
    Return {'error': ...} on error
    """

    # NOTE: we want to match the empty string too
    base64_pattern = '^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$'

    zonefiles_schema = {
        'type': 'object',
        'properties': {
            'zonefiles': {
                'type': 'object',
                'patternProperties': {
                    OP_ZONEFILE_HASH_PATTERN: {
                        'type': 'string',
                        'pattern': base64_pattern
                    },
                },
            },
        },
        'required': [
            'zonefiles',
        ]
    }

    schema = json_response_schema( zonefiles_schema )

    if proxy is None:
        host, port = url_to_host_port( hostport )
        assert host is not None and port is not None
        proxy = BlockstackRPCClient( host, port, timeout=timeout, src=my_hostport )

    zonefiles = None
    try:
        zf_payload = proxy.get_zonefiles( zonefile_hashes )
        zf_payload = json_validate( schema, zf_payload )
        if json_is_error( zf_payload ):
            return zf_payload 

        decoded_zonefiles = {}

        for zf_hash, zf_data_b64 in zf_payload['zonefiles'].items():
            zf_data = base64.b64decode( zf_data_b64 )
            assert storage.verify_zonefile( zf_data, zf_hash ), "Zonefile data mismatch"

            # valid 
            decoded_zonefiles[ zf_hash ] = zf_data

        # return this 
        zf_payload['zonefiles'] = decoded_zonefiles
        zonefiles = zf_payload

    except AssertionError, ae:
        log.exception(ae)
        zonefiles = {'error': 'Zonefile data mismatch'}

    except ValidationError, ve:
        log.exception(ve)
        zonefiles = json_traceback()

    return zonefiles


def put_zonefiles( hostport, zonefile_data_list, timeout=30, my_hostport=None, proxy=None ):
    """
    Push one or more zonefiles to the given server.
    Return {'status': True, 'saved': [...]} on success
    Return {'error': ...} on error
    """
    saved_schema = {
        'type': 'object',
        'properties': {
            'saved': {
                'type': 'array',
                'items': {
                    'type': 'integer',
                    'minItems': len(zonefile_data_list),
                    'maxItems': len(zonefile_data_list)
                },
            },
        },
        'required': [
            'saved'
        ]
    }

    schema = json_response_schema( saved_schema )

    if proxy is None:
        host, port = url_to_host_port( hostport )
        assert host is not None and port is not None
        proxy = BlockstackRPCClient( host, port, timeout=timeout, src=my_hostport )

    push_info = None
    try:
        push_info = proxy.put_zonefiles( zonefile_data_list )
        push_info = json_validate( schema, push_info )
        if json_is_error( push_info ):
            return push_info
        
    except ValidationError as e:
        log.exception(e)
        push_info = json_traceback()

    return push_info 
