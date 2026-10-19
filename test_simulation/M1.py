# ---------------------TASK 1-------------------------
# TurboBlom needs a big table of random-looking numbers called the key matrix. Every node in the network gets some rows from this table. 
# Two nodes can derive a shared secret key from the rows they have in common. Your job is to generate this table.

import hmac, hashlib

# m --> no. of rows, seed --> 32-byte sectret message
def generate_key_matrix(m, seed):

    key_matrix = []

    for i in range(m):
        row_i = hmac.new(seed, b'row' + i.to_bytes(2, 'big'), hashlib.sha256).digest()
        key_matrix.append(row_i); 

    return key_matrix

seed = bytes(range(32))
secret_matrix = generate_key_matrix(50, seed)
print(len(secret_matrix))
print(len(secret_matrix[0]))
print(secret_matrix[0].hex())


#(Just has time so did other people tasks as well)
# --------------------TASK 2--------------------------
# Each node in the network is assigned k=5 'spaces' out of the 50 available. 
# Two nodes can only share a key if they have at least one space in common. Your job is to deterministically assign spaces to nodes.

# node_id :- which node(1, 2, ...)
# k :- how many spaces to assign (in this case 5)
# m :- total spaces avaiable (in this case 50)
# K_master :- 32-byte master key

#the function returens a list of k unique integers
# def assign_spaces(node_id, k, m, K_master):
#     num_node_list = []

#     h = hmac.new(K_master, b'spaces' + node_id.to_bytes(2, 'big'), hashlib.sha256).digest()
#     for a in range(k):
#         for i in h:
#             if(i%m not in num_node_list):
#                 num_node_list.append(i%m)
#                 break

#     return num_node_list

#---------------------TASK 3---------------------------
# Once two nodes know which spaces they share, they derive a secret key from those spaces using HMAC. This is the actual TurboBlom key 
# derivation step. Neither node ever transmits this key — they both compute it independently and arrive at the same result.

# Parameters set for the function are :- node_id_a, node_id_b, K_master, spaces_a, spaces_b
# def compute_K_AB(node_id_a, node_id_b, K_master, spaces_a, spaces_b):
#     shared = sorted(set(spaces_a) & set(spaces_b))
#     if(shared == []):
#         return None
    
#     id_low = min(node_id_a, node_id_b)
#     id_high = max(node_id_a, node_id_b)

#     result = bytes(16)
#     for space_id in shared:
#         msg = id_low.to_bytes(2, 'big') + id_high.to_bytes(2, 'big') + space_id.to_bytes(2, 'big')
#         sub_key = hmac.new(K_master, msg, hashlib.sha256).digest()[:16]

#     result = bytes(a^b for a, b in zip(result, sub_key))
#     return result

# K = bytes(32)
# spaces_a = assign_spaces(1, 5, 50, K)   # M2's function
# spaces_b = assign_spaces(4, 5, 50, K)

# key_ab = compute_K_AB(1, 4, K, spaces_a, spaces_b)
# key_ba = compute_K_AB(4, 1, K, spaces_b, spaces_a)

# print(key_ab.hex())   