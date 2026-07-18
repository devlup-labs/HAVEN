import hmac
import hashlib
import secrets

def send_hello_req(node_id_a: int, node_id_b: int, K_AB: bytes) -> dict:
    nonce_a = secrets.token_bytes(16)
    msg = (b'HELLO_REQ' + 
           node_id_a.to_bytes(2, 'big') + 
           node_id_b.to_bytes(2, 'big') + 
           nonce_a)
    mac = hmac.new(K_AB, msg, hashlib.sha256).digest()[:16]
    return {
        'node_id_a': node_id_a,
        'node_id_b': node_id_b,
        'nonce_a': nonce_a,
        'mac': mac
    }
def test():
    K_AB = b"key" # just a testing byte string for key
    req1 = send_hello_req(1, 2, K_AB)
    req2 = send_hello_req(1, 2, K_AB)
    print(req1['nonce_a'].hex())   # different every time
    print(req2['nonce_a'].hex())   # different from req1
    assert req1['nonce_a'] != req2['nonce_a']   # MUST PASS
    assert len(req1['mac']) == 16 
    print("M1 test pass")
test()

def send_hello_resp(node_id_b: int, node_id_a: int, K_AB: bytes, hello_req: dict) -> dict | None:
  pass
  msg = (b'HELLO_REQ' 
           + node_id_a.to_bytes(2, 'big') 
           + node_id_b.to_bytes(2, 'big') 
           + hello_req['nonce_a'])
  expected_mac = hmac.new(K_AB, msg, hashlib.sha256).digest()[:16]
  if not hmac.compare_digest(expected_mac, hello_req['mac']):
        return None
  nonce_b = secrets.token_bytes(16)
  resp_msg = (b'HELLO_RESP' 
                + node_id_b.to_bytes(2, 'big') 
                + node_id_a.to_bytes(2, 'big') 
                + hello_req['nonce_a'] 
                + nonce_b)
  mac_b = hmac.new(K_AB, resp_msg, hashlib.sha256).digest()[:16]
  return {
        'node_id_b': node_id_b, 
        'nonce_a': hello_req['nonce_a'],
        'nonce_b': nonce_b, 
        'mac': mac_b
    }

def test_hello_resp():
    K_AB = b"key"
    req = send_hello_req(1, 2, K_AB)
    
    # Happy Path
    resp = send_hello_resp(2, 1, K_AB, req)
    assert resp is not None
    
    # Tamper test 
    bad_req = dict(req)
    bad_req['mac'] = bytes([req['mac'][0] ^ 0xFF]) + req['mac'][1:]
    assert send_hello_resp(2, 1, K_AB, bad_req) is None # MUST PASS

    print("M2 test pass")

test_hello_resp()

def verify_hello_resp(node_id_a: int, K_AB: bytes, nonce_a: bytes, hello_resp: dict) -> dict | None:
    node_id_b = hello_resp['node_id_b']

    if hello_resp['nonce_a'] != nonce_a:
        return None   

    resp_msg = (b'HELLO_RESP'
                + node_id_b.to_bytes(2, 'big')
                + node_id_a.to_bytes(2, 'big')
                + nonce_a
                + hello_resp['nonce_b'])
    expected = hmac.new(K_AB, resp_msg, hashlib.sha256).digest()[:16]

    if not hmac.compare_digest(expected, hello_resp['mac']):
        return None

    return {'node_id': node_id_b, 'K_AB': K_AB,
            'session_epoch': 0, 'miss_count': 0}

def test_verify_hello_resp():
    K_AB = bytes(range(16))
    req    = send_hello_req(1, 2, K_AB)
    resp   = send_hello_resp(2, 1, K_AB, req)
    entry  = verify_hello_resp(1, K_AB, req['nonce_a'], resp)
    assert entry is not None
    assert entry['node_id'] == 2
    print('Neighbor table entry:', entry)
    entry2 = verify_hello_resp(1, K_AB, secrets.token_bytes(16), resp)
    assert entry2 is None
    print("M3 test pass")

test_verify_hello_resp()
