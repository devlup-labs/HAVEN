from hello import hello_req, hello_resp, verify_hello_resp
from turboblom import assign_spaces, compute_K_AB

import networkx as nx

K_master = bytes(range(32))

G = nx.random_geometric_graph(50, 0.25)
spaces = {n: assign_spaces(n, 5, 50, K_master) for n in G.nodes()}

total = 0
authenticated = 0
failed_no_spaces = 0
failed_bad_mac = 0

for u, v in G.edges():
    total = total + 1
    K_AB = compute_K_AB(u, v, K_master, spaces[u], spaces[v])
    if K_AB is None:
        failed_no_spaces = failed_no_spaces + 1
        continue

    req = hello_req(u, v, K_AB)
    resp = hello_resp(u, v, K_AB, req)

    if resp is None:
        failed_no_spaces = failed_no_spaces + 1
        continue

    entry = verify_hello_resp(u, K_AB, req['nonce_a'], resp)
    if entry is not None:
        authenticated = authenticated + 1

print(f'Total pairs in range:  {total}')
print(f'Authenticated:         {authenticated}')
print(f'Failed (no spaces):    {failed_no_spaces}')
print(f'Failed (bad MAC):      {failed_bad_mac}')

