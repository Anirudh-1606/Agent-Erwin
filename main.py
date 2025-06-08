from growwapi import GrowwAPI

import os
print("Ready to Groww!")
token = os.environ["GROWW_API_TOKEN"]
groww = GrowwAPI(token)
try:
    print("Calling groww.get_holdings_for_user...")
    holdings = groww.get_holdings_for_user(timeout=8)
    print("RESULT:", holdings)
except Exception as e:
    print("Error:", e)
