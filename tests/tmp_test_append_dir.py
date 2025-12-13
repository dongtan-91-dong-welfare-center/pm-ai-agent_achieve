from pathlib import Path
from data_loader import core as dl_core
from data_loader import config as dl_conf

TMP = Path('tmp_test_data_dir')
TMP.mkdir(exist_ok=True)
dl_conf.DATA_DIR = str(TMP)

rows = [{'po_id':'PO-XY-1','po_item_no':1,'vendor_id':'V001','product_id':'9309896','po_date':'2025-10-10','schedule_qty':10,'received_qty':0,'delivery_date':'2025-11-01'}]
ok, msg = dl_core.append_purchase_order_rows(rows)
print('append ok', ok, msg)
print('file exists?', (TMP / 'purchase_order.csv').exists())
