#from bcast.bcast.celery import add
#
#result = add.delay(4, 6)
#print(f"Task state: {result.state}")  # Outputs 'PENDING' initially
#
## Wait for the result
#output = result.get(timeout=10)
#print(f"Task result: {output}")  # Outputs '10'