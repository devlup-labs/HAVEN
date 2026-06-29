import hmac
import hashlib

# **************** M2 ****************
def assign_spaces(node_id: int, k: int, m: int, K_master: bytes) -> list[int]:
    message = b'spaces' + node_id.to_bytes(2, 'big')
    h = hmac.new(K_master, message, hashlib.sha256).digest()
    
    spaces = []
    seen = set()
    for byte in h:
        index = byte % m
        if index not in seen:
            seen.add(index)
            spaces.append(index)

            if len(spaces) == k:
                break
    return spaces 

# **************** M3 ****************
def compute_K_AB(node_id_a: int, node_id_b: int, K_master: bytes, spaces_a: list[int], spaces_b: list[int]):
    shared = sorted(set(spaces_a) & set(spaces_b))
    
    if not shared:
        return None
        
    id_low = min(node_id_a, node_id_b)
    id_high = max(node_id_a, node_id_b)
    
    result = bytes(16) 
    
    for space_idx in shared: 
        msg = (id_low.to_bytes(2, 'big') + 
               id_high.to_bytes(2, 'big') + 
               space_idx.to_bytes(2, 'big'))
        
        sub_key = hmac.new(K_master, msg, hashlib.sha256).digest()[:16]
        result = bytes(a ^ b for a, b in zip(result, sub_key))
        
    return result

def test_M2_M3():
    print("\n--- Running M3 Tests ---")
    K = bytes(range(32))
    
    spaces_a = assign_spaces(1, 5, 50, K)
    spaces_b = assign_spaces(2, 5, 50, K)

    print(f"Node 1 spaces: {spaces_a}")
    print(f"Node 2 spaces: {spaces_b}")

    key_ab = compute_K_AB(1, 2, K, spaces_a, spaces_b)
    key_ba = compute_K_AB(2, 1, K, spaces_b, spaces_a)

    if key_ab is None:
        print("Nodes 1 and 2 do not share any spaces. No key generated.")
        return 0

    print(f"Key A->B: {key_ab.hex()}")
    print(f"Key B->A: {key_ba.hex()}")
    
    assert key_ab == key_ba  
    assert len(key_ab) == 16 
    
    # M3 CONFIRMATION CHECK
    print("--> M3 Confirmation: compute_K_AB works perfectly! Keys match.")
    
    return 0

# **************** TESTING ****************
if __name__ == '__main__':
    print("--- Running M2 Tests ---")
    K = bytes(range(32))
    s1 = assign_spaces(1, 5, 50, K)
    
    print(f"Assigned spaces for Node 1: {s1}")
    
    assert len(s1) == 5
    assert len(set(s1)) == 5 
    
    # M2 CONFIRMATION CHECK
    print("--> M2 Confirmation: assign_spaces generated exactly 5 unique spaces!")
    
    # Run M3 tests
    test_M2_M3()
