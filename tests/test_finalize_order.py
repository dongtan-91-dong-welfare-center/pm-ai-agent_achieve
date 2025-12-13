import pandas as pd
import os
os.environ.setdefault('GOOGLE_API_KEY', 'dummy')
os.environ.setdefault('MODEL', 'test-model')
from data_loader import core as dl_core
from data_loader import config as dl_conf
from core.nodes import finalize_order


def test_append_purchase_order_rows(tmp_path, monkeypatch):
    # Prepare temp data dir and override DATA_DIR
    temp_data = tmp_path / "data"
    temp_data.mkdir()
    monkeypatch.setattr(dl_conf, 'DATA_DIR', str(temp_data))

    # Create one dummy purchase order row
    rows = [{
        'po_id': 'PO1234',
        'item_no': 1,
        'vendor_id': 'V001',
        'product_id': '9309896',
        'po_date': '2025-10-01',
        'schedule_qty': 100,
        'received_qty': 0,
        'delivery_date': '2025-10-10'
    }]

    success, msg = dl_core.append_purchase_order_rows(rows)
    assert success
    file_path = temp_data / 'purchase_order.csv'
    assert file_path.exists()

    df = pd.read_csv(file_path)
    assert not df.empty
    assert df['po_id'].iloc[0] == 'PO1234'


def test_finalize_order_node(tmp_path, monkeypatch):
    # Prepare temp data dir and override DATA_DIR
    temp_data = tmp_path / "data"
    temp_data.mkdir()
    monkeypatch.setattr(dl_conf, 'DATA_DIR', str(temp_data))

    # Create a sample dataframe to serve as last_run_result
    sample = pd.DataFrame([
        {
            'po_id': 'PO9999',
            'item_no': 1,
            'vendor_id': 'V002',
            'product_id': '9309999',
            'po_date': '2025-11-01',
            'schedule_qty': 50,
            'received_qty': 0,
            'delivery_date': '2025-11-15'
        }
    ])

    serial = {
        'type': 'dataframe',
        'data': sample.to_dict(orient='split')
    }

    state = {
        'execution_status': 'approved',
        'analysis_data': {'last_run_result': serial},
        'user_approval_pending': False,
        'user_approval_decision': 'approve'
    }

    result = finalize_order(state)
    assert '반영' in result['messages'][0].content or '저장' in result['messages'][0].content
    # Ensure that the post-action continue prompt is included
    assert any('계속 반복하시겠습니까' in m.content for m in result['messages'])

    # Verify file
    file_path = temp_data / 'purchase_order.csv'
    assert file_path.exists()
    df = pd.read_csv(file_path)
    assert 'PO9999' in df['po_id'].astype(str).values


def test_submit_purchase_order_tool(tmp_path, monkeypatch):
    # Prepare temp data dir
    temp_data = tmp_path / "data"
    temp_data.mkdir()
    monkeypatch.setattr(dl_conf, 'DATA_DIR', str(temp_data))

    import tools
    sample = {
        'po_id': 'PO-TOOL-1',
        'item_no': 1,
        'vendor_id': 'V001',
        'product_id': '9301111',
        'po_date': '2025-12-01',
        'schedule_qty': 5,
        'received_qty': 0,
        'delivery_date': '2025-12-10'
    }

    result = tools.submit_purchase_order_sync(sample)
    assert '저장' in result or '정상' in result

    file_path = temp_data / 'purchase_order.csv'
    assert file_path.exists()
    df = pd.read_csv(file_path)
    assert 'PO-TOOL-1' in df['po_id'].astype(str).values
