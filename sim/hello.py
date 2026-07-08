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
    print("test successfull")
test()
