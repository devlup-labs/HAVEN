import hmac
import hashlib

#M3
def compute_K_AB(node_id_a: int, node_id_b: int, K_master: bytes, spaces_a: list[int], spaces_b: list[int]):
  shared = sorted(set(spaces_a) & set(spaces_b))
  if not shared:
        return None
  id_low = min(node_id_a, node_id_b)
  id_high = max(node_id_a, node_id_b)
  result = bytes(16) # xor of any number with 0 gives the number itself this acts as our starter 
  for space_idx in shared: # this will convert the numbers or ids into 2 bytes . eg if 2 were to be passed then it will be converted to 02
        msg = (id_low.to_bytes(2, 'big') + 
               id_high.to_bytes(2, 'big') + 
               space_idx.to_bytes(2, 'big'))
        sub_key = hmac.new(K_master, msg, hashlib.sha256).digest()[:16]
        result = bytes(a ^ b for a, b in zip(result, sub_key))
  return result
def test_M2_M3():
  K = bytes(range(32))
  spaces_a =  assign_space(1, 5, 50, K)    # M2's function
  spaces_b =  assign_space(2, 5, 50, K) 

  key_ab = compute_K_AB(1, 2, K, spaces_a, spaces_b)
  key_ba = compute_K_AB(2, 1, K, spaces_b, spaces_a)
  
  if(key_ab == None):
    print("no space matched")
    print(assign_space(1,5,50,K) ,"space 1")
    print(assign_space(2,5,50,K),"space 2")
    return 0
  

  print(key_ab.hex())
  print(key_ba.hex())
  assert key_ab == key_ba   # THIS MUST PASS
  assert len(key_ab) == 16 
  return 0


# # ****************M2************
def assign_space(node_id: int,k:int, m:int ,K_master :bytes) -> list[int]:

  message = b'spaces' + node_id.to_bytes(2, 'big')
  h = hmac.new(K_master, message, hashlib.sha256).digest()
 
  spaces=[]
  seen=set()
  for byte in h:
    index= byte%m;
    if index  not in seen:
      seen.add(index)
      spaces.append(index)

      if(len(spaces)==k):
        break
  return spaces 


def assign_spaces(node_id: int,k:int, m:int ,K_master :bytes) -> list[int]:

  message = b'spaces' + node_id.to_bytes(2, 'big')
  h = hmac.new(K_master, message, hashlib.sha256).digest()
 
  spaces=[]
  seen=set()
  for byte in h:
    index= byte%m;
    if index  not in seen:
      seen.add(index)
      spaces.append(index)

      if(len(spaces)==k):
        break
  return spaces 
  

  # testing
if __name__ == '__main__':
    K = bytes(range(32))
    s1 = assign_spaces(1, 5, 50, K)
    
    # Actually print the result so you can see it
    print(f"Assigned spaces for Node 1: {s1}")
    
    assert len(s1)==5
    assert len(set(s1))==5 

    print("Pass")
         
test_M2_M3()    
