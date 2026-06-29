import hmac
import hashlib

def generate_key_matrix(m: int, seed: bytes) -> list[bytes]:
    """
    Takes an integer m and a 32-byte seed (bytes).
    Returns a list of m rows, each row being 32 random-looking bytes
    derived from the seed using HMAC-SHA256.
    """
    matrix = []
    for i in range(m):
        # Derive 32 bytes for each row using HMAC-SHA256 with seed as key
        # and the row index as message.
        msg = i.to_bytes(4, 'big')
        row = hmac.new(seed, msg, hashlib.sha256).digest()
        matrix.append(row)
    return matrix

def assign_spaces(node_id: int, k: int, m: int, K_master: bytes) -> list[int]:
    """
    Given a node's ID, pick k unique space indices (0 to m-1) for that node.
    The selection is deterministic and uses HMAC-SHA256.
    """
    spaces = []
    seen = set()
    counter = 0
    # Loop to ensure we get exactly k unique spaces even if collisions occur
    while len(spaces) < k:
        msg = b'spaces' + node_id.to_bytes(4, 'big') + counter.to_bytes(4, 'big')
        h = hmac.new(K_master, msg, hashlib.sha256).digest()
        for byte in h:
            idx = byte % m
            if idx not in seen:
                seen.add(idx)
                spaces.append(idx)
                if len(spaces) == k:
                    break
        counter += 1
    return sorted(spaces)

def compute_K_AB(node_a: int, node_b: int, matrix: list[bytes], spaces_a: list[int], spaces_b: list[int]) -> bytes:
    """
    Find which spaces node_a and node_b share.
    XOR together the matrix rows at those shared indices.
    Hash the result (mixing in node IDs for pair uniqueness) to get a 16-byte key.
    """
    shared = set(spaces_a) & set(spaces_b)
    if not shared:
        return None
    
    # XOR the rows corresponding to shared spaces
    xor_sum = bytearray(32)
    for idx in sorted(shared):
        row = matrix[idx]
        for i in range(32):
            xor_sum[i] ^= row[i]
            
    # Mix in node IDs to make the key unique to this pair of nodes and symmetric
    id_low = min(node_a, node_b)
    id_high = max(node_a, node_b)
    msg = xor_sum + id_low.to_bytes(4, 'big') + id_high.to_bytes(4, 'big')
    
    # Hash to get a 16-byte key
    return hashlib.sha256(msg).digest()[:16]

if __name__ == '__main__':
    print("--- Running TurboBlom Self-Tests ---")
    
    # Test Seed and Master Key
    some_seed = bytes(range(32))
    K_master = bytes(range(32, 64))
    
    # 1. Key Matrix Generation
    matrix = generate_key_matrix(50, some_seed)
    print(f"Matrix generated with {len(matrix)} rows.")
    print(f"First row (hex): {matrix[0].hex()}")
    
    # 2. Space Assignment
    spaces_1 = assign_spaces(1, 5, 50, K_master)
    spaces_2 = assign_spaces(2, 5, 50, K_master)
    print(f"Node 1 spaces: {spaces_1} (unique: {len(set(spaces_1)) == len(spaces_1)})")
    print(f"Node 2 spaces: {spaces_2} (unique: {len(set(spaces_2)) == len(spaces_2)})")
    
    # 3. Pairwise Key Derivation
    key_12 = compute_K_AB(1, 2, matrix, spaces_1, spaces_2)
    key_21 = compute_K_AB(2, 1, matrix, spaces_2, spaces_1)
    
    if key_12 is not None:
        print(f"K_12 (hex): {key_12.hex()}")
        print(f"K_21 (hex): {key_21.hex()}")
        assert key_12 == key_21, "Symmetric key derivation failed!"
        assert len(key_12) == 16, "Key length must be 16 bytes!"
        print("Assert key_12 == key_21 passed.")
    else:
        print("Nodes 1 and 2 do not share any spaces.")
