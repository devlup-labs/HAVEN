import pytest
from sim.turboblom import generate_key_matrix, assign_spaces, compute_K_AB

def test_generate_key_matrix():
    seed = bytes(range(32))
    m = 50
    matrix = generate_key_matrix(m, seed)
    
    assert len(matrix) == m
    assert all(isinstance(row, bytes) and len(row) == 32 for row in matrix)
    
    # Verify determinism
    matrix2 = generate_key_matrix(m, seed)
    assert matrix == matrix2
    
    # Verify different seed gives different matrix
    diff_seed = bytes([1] * 32)
    matrix_diff = generate_key_matrix(m, diff_seed)
    assert matrix != matrix_diff

def test_assign_spaces():
    K_master = bytes(range(32, 64))
    m = 50
    k = 5
    
    spaces_1 = assign_spaces(1, k, m, K_master)
    spaces_2 = assign_spaces(2, k, m, K_master)
    
    assert len(spaces_1) == k
    assert len(set(spaces_1)) == k  # No duplicates
    assert all(0 <= s < m for s in spaces_1)
    
    # Verify determinism
    spaces_1_retry = assign_spaces(1, k, m, K_master)
    assert spaces_1 == spaces_1_retry
    
    # Node 1 and Node 2 should get different spaces (with high probability)
    assert spaces_1 != spaces_2

def test_compute_K_AB():
    seed = bytes(range(32))
    K_master = bytes(range(32, 64))
    m = 50
    k = 5
    
    matrix = generate_key_matrix(m, seed)
    
    # Test with nodes sharing spaces
    # Let's find two node IDs that share at least one space
    shared_found = False
    for i in range(1, 100):
        for j in range(i+1, 100):
            sa = assign_spaces(i, k, m, K_master)
            sb = assign_spaces(j, k, m, K_master)
            if set(sa) & set(sb):
                key_ab = compute_K_AB(i, j, matrix, sa, sb)
                key_ba = compute_K_AB(j, i, matrix, sb, sa)
                assert key_ab == key_ba
                assert len(key_ab) == 16
                shared_found = True
                break
        if shared_found:
            break
    assert shared_found, "Could not find a pair sharing spaces for test"
    
    # Test with nodes NOT sharing spaces
    # Let's find two node IDs that do NOT share any space
    unshared_found = False
    for i in range(1, 100):
        for j in range(i+1, 100):
            sa = assign_spaces(i, k, m, K_master)
            sb = assign_spaces(j, k, m, K_master)
            if not (set(sa) & set(sb)):
                key_ab = compute_K_AB(i, j, matrix, sa, sb)
                assert key_ab is None
                unshared_found = True
                break
        if unshared_found:
            break
    assert unshared_found, "Could not find a pair not sharing spaces for test"
