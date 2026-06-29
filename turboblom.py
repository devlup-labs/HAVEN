
#M3
def compute_K_AB(node_a, node_b, matrix ,spaces_a, spaces_b):
    


# ****************M2************
import hmac
import hashlib

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
import hmac
import hashlib

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
         
    
