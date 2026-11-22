from fastapi.testclient import TestClient
from main import create_app


def test_workflow_lifecycle(tmp_path):
    client = TestClient(create_app(tmp_path / 'test.db'))
    case = client.post('/api/cases', json={'title':'Demo purchase','description':'Synthetic request','amount':2000,'owner':'Demo agent'}).json()
    assert case['approval_required']
    path = f"/api/cases/{case['id']}"
    send = lambda action, note='': client.post(path+'/actions',json={'action':action,'actor':'Demo reviewer','note':note})
    assert send('advance').json()['stage'] == 'Review'
    assert send('advance').json()['stage'] == 'Approval'
    assert send('advance').status_code == 409
    assert send('approve').json()['status'] == 'Completed'
    assert send('approve').status_code == 409
    assert len(client.get(path).json()['history']) == 4
    assert 'completed' in client.get(path+'/summary').json()['summary']


def test_decision_and_version_snapshot(tmp_path):
    client = TestClient(create_app(tmp_path / 'test.db'))
    payload={'title':'Demo request','description':'','amount':100,'owner':'Demo agent'}
    old=client.post('/api/cases',json=payload).json()
    assert 'Approval' not in old['stages']
    wf={'stages':['Submitted','Approval','Review','Completed'],'approval_threshold':50,'sla_hours':24}
    assert client.put('/api/workflow',json=wf).status_code == 200
    new=client.post('/api/cases',json=payload).json()
    assert 'Approval' in new['stages']
    assert 'Approval' not in client.get(f"/api/cases/{old['id']}").json()['stages']
    path=f"/api/cases/{new['id']}/actions"
    assert client.post(path,json={'action':'advance','actor':'Demo'}).json()['stage']=='Approval'
    assert client.post(path,json={'action':'reject','actor':'Demo'}).status_code==422
    assert client.post(path,json={'action':'reject','actor':'Demo','note':'Missing documentation'}).json()['status']=='Rejected'
