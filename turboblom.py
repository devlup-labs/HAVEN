import hashlib 
# node_a: int, node_b: int, matrix: list[bytes], spaces_a: list[int], spaces_b: list[int]) -> bytes
def compute_K_AB(node_a, node_b, matrix ,spaces_a, spaces_b):
    shared = [s for s in spaces_a if s in spaces_b]
    print(shared)


