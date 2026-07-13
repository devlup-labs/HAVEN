import hmac, hashlib, secrets

# Creating the Hello Request function 
def hello_req(node_id_a, node_id_b, K_AB):
    nonce_a = secrets.token_bytes(16)
    msg = (b'HELLO_REQ' + node_id_a.to_bytes(2, 'big') + node_id_b.to_bytes(2, 'big') + nonce_a)
    mac = hmac.new(K_AB, msg, hashlib.sha256).digest()[:16]
    return {
        'node_id_a': node_id_a,
        'node_id_b': node_id_b,
        'nonce_a': nonce_a,
        'mac': mac
    }

# Creating the Hello Response function & verifying the hello request as well
def hello_resp(node_id_a, node_id_b, K_AB, hello_req):
    msg = (b'HELLO_REQ' + node_id_a.to_bytes(2, 'big') + node_id_b.to_bytes(2, 'big') + hello_req['nonce_a'])
    mac = hmac.new(K_AB, msg, hashlib.sha256).digest()[:16]

    if not hmac.compare_digest(mac,  hello_req['mac']):
        return None
    
    nonce_b = secrets.token_bytes(16)
    resp_msg = (b'HELLO_RESP' + node_id_a.to_bytes(2, 'big') + node_id_b.to_bytes(2, 'big') + hello_req['nonce_a'] + nonce_b)
    mac_b = hmac.new(K_AB, resp_msg, hashlib.sha256).digest()[:16]

    return {
        'node_id_b': node_id_b, 
        'nonce_a': hello_req['nonce_a'],
        'nonce_b': nonce_b, 
        'mac': mac_b,
    }

# Verifying the Hello Response itself
def verify_hello_resp(node_id_a, K_AB, nonce_a, hello_resp):
    node_id_b = hello_resp['node_id_b']

    if hello_resp['nonce_a'] != nonce_a:
        return None
    
    resp_msg = b'HELLO_RESP' + node_id_a.to_bytes(2, 'big') + node_id_b.to_bytes(2, 'big') + nonce_a + hello_resp['nonce_b']
    expected_mac = hmac.new(K_AB, resp_msg, hashlib.sha256).digest()[:16]

    if not hmac.compare_digest(expected_mac, hello_resp['mac']):
        return None 
    
    return {
        'node_id_a': node_id_a,
        'node_id_b': node_id_b,
        'K_AB': K_AB,
        'session_epoch': 0,
        'miss_count': 0,
    }