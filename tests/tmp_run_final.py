from pathlib import Path
import os
os.environ.setdefault('GOOGLE_API_KEY', 'dummy')
os.environ.setdefault('MODEL', 'test-model')
from data_loader import core as dl_core
from data_loader import config as dl_conf
try:
    from core.nodes import finalize_order
except Exception as e:
    print('Failed to import agent_nodes:', type(e), e)
    raise
import pandas as pd

# Setup
print('Start tmp_run_final')
TMP = Path('tmp_test_data')
if not TMP.exists(): TMP.mkdir()
# Overwrite DATA_DIR in module (Note: core references config.DATA_DIR during runtime; overriding here will affect subsequent calls)
dl_conf.DATA_DIR = str(TMP)

rows = [{'po_id':'PO-XY-1','item_no':1,'vendor_id':'V001','product_id':'9309896','po_date':'2025-10-10','schedule_qty':10,'received_qty':0,'delivery_date':'2025-11-01'}]

print('Appending purchase orders...')
ok, msg = dl_core.append_purchase_order_rows(rows)
print('append ok', ok, msg)

# Now call finalize_order using a df serialized
sample = pd.DataFrame(rows)
serial = {'type':'dataframe','data': sample.to_dict(orient='split')}
state = {'execution_status':'approved','analysis_data':{'last_run_result':serial},'user_approval_pending': False, 'user_approval_decision':'approve'}
print('Calling finalize_order...')
res = finalize_order(state)
print('finalize result:', res)

# Verify file
from csv import DictReader
fp = TMP / 'purchase_order.csv'
print('file exists:', fp.exists())
if fp.exists():
    with open(fp,'r',encoding='utf-8') as f:
        dr = list(DictReader(f))
        print('rows in file:', len(dr), dr[0] if dr else None)
