"""FlowForge: local demonstration BPM engine with transactional case history."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).parent
DEFAULT_STAGES = ['Submitted', 'Review', 'Approval', 'Completed']


def now():
    return datetime.now(timezone.utc)


class Workflow(BaseModel):
    stages: list[str] = Field(min_length=3, max_length=12)
    approval_threshold: float = Field(ge=0, le=1e9)
    sla_hours: int = Field(ge=1, le=720)

    @field_validator('stages')
    @classmethod
    def validate_stages(cls, value):
        stages = [stage.strip() for stage in value]
        if any(not s or len(s) > 40 for s in stages) or len(set(stages)) != len(stages):
            raise ValueError('Stage names must be unique and 1–40 characters')
        if stages[0] != 'Submitted' or stages[-1] != 'Completed' or 'Approval' not in stages:
            raise ValueError('Start with Submitted, include Approval and end with Completed')
        return stages


class NewCase(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=3000)
    amount: float = Field(ge=0, le=1e9)
    owner: str = Field(min_length=1, max_length=80)


class Action(BaseModel):
    action: str
    actor: str = Field(min_length=1, max_length=80)
    note: str = Field(default='', max_length=500)


def create_app(db_path=None):
    app = FastAPI(title='FlowForge BPM', version='0.1.0')
    path = str(db_path or os.environ.get('FLOWFORGE_DB', ROOT / 'flowforge.db'))

    @contextmanager
    def connect():
        with sqlite3.connect(path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            yield conn

    with connect() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS workflow(id INTEGER PRIMARY KEY CHECK(id=1), stages TEXT NOT NULL, threshold REAL NOT NULL, sla INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL, owner TEXT NOT NULL, stages TEXT NOT NULL, step INTEGER NOT NULL, status TEXT NOT NULL, approval_required INTEGER NOT NULL, created TEXT NOT NULL, due TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id), event TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL);
        ''')
        conn.execute('INSERT OR IGNORE INTO workflow VALUES(1,?,?,?)', (json.dumps(DEFAULT_STAGES), 1000, 48))

    def read_workflow(conn):
        row = conn.execute('SELECT * FROM workflow WHERE id=1').fetchone()
        return {'stages': json.loads(row['stages']), 'approval_threshold': row['threshold'], 'sla_hours': row['sla']}

    def serialize(row):
        data = dict(row)
        data['stages'] = json.loads(data['stages'])
        data['stage'] = data['stages'][data['step']]
        data['overdue'] = data['status'] == 'Open' and datetime.fromisoformat(data['due']) < now()
        data['approval_required'] = bool(data['approval_required'])
        return data

    def get_case(conn, case_id):
        row = conn.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Case not found')
        return row

    def audit(conn, case_id, event, actor, note=''):
        conn.execute('INSERT INTO history(case_id,event,actor,note,created) VALUES(?,?,?,?,?)', (case_id,event,actor,note,now().isoformat()))

    @app.get('/api/workflow')
    def workflow():
        with connect() as conn:
            return read_workflow(conn)

    @app.put('/api/workflow')
    def update_workflow(payload: Workflow):
        with connect() as conn:
            conn.execute('UPDATE workflow SET stages=?,threshold=?,sla=? WHERE id=1', (json.dumps(payload.stages),payload.approval_threshold,payload.sla_hours))
            return read_workflow(conn)

    @app.get('/api/cases')
    def list_cases():
        with connect() as conn:
            return [serialize(row) for row in conn.execute('SELECT * FROM cases ORDER BY id DESC')]

    @app.post('/api/cases', status_code=201)
    def create_case(payload: NewCase):
        with connect() as conn:
            wf = read_workflow(conn)
            required = payload.amount >= wf['approval_threshold']
            stages = [s for s in wf['stages'] if required or s != 'Approval']
            created = now()
            cur = conn.execute('INSERT INTO cases(title,description,amount,owner,stages,step,status,approval_required,created,due) VALUES(?,?,?,?,?,0,?,?,?,?)', (payload.title,payload.description,payload.amount,payload.owner,json.dumps(stages),'Open',int(required),created.isoformat(),(created + timedelta(hours=wf['sla_hours'])).isoformat()))
            audit(conn,cur.lastrowid,'Created',payload.owner,'Approval required' if required else 'Approval bypassed by decision rule')
            return serialize(get_case(conn,cur.lastrowid))

    @app.get('/api/cases/{case_id}')
    def case_detail(case_id: int):
        with connect() as conn:
            data = serialize(get_case(conn,case_id))
            data['history'] = [dict(row) for row in conn.execute('SELECT event,actor,note,created FROM history WHERE case_id=? ORDER BY id',(case_id,))]
            return data

    @app.post('/api/cases/{case_id}/actions')
    def transition(case_id: int, payload: Action):
        with connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            case = serialize(get_case(conn,case_id))
            if case['status'] != 'Open':
                raise HTTPException(409,'Case has already closed')
            current = case['stage']
            step = case['step']
            if current == 'Approval' and payload.action == 'reject':
                if not payload.note.strip():
                    raise HTTPException(422,'Rejection requires a note')
                status = 'Rejected'
            elif (current == 'Approval' and payload.action == 'approve') or (current != 'Approval' and payload.action == 'advance'):
                step += 1
                status = 'Completed' if step == len(case['stages'])-1 else 'Open'
            else:
                raise HTTPException(409,'Action is not valid for this stage')
            conn.execute('UPDATE cases SET step=?, status=? WHERE id=?',(step,status,case_id))
            audit(conn,case_id,f'{current}: {payload.action}',payload.actor,payload.note)
            return serialize(get_case(conn,case_id))

    @app.get('/api/cases/{case_id}/summary')
    def summary(case_id: int):
        with connect() as conn:
            case = serialize(get_case(conn,case_id))
            return {'summary': f"{case['title']} is {case['status'].lower()} at {case['stage']}. Owner: {case['owner']}. Amount: ${case['amount']:,.2f}. Approval {'required' if case['approval_required'] else 'not required'}. SLA {'overdue' if case['overdue'] else 'not overdue'}."}

    dist = ROOT / 'frontend' / 'dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist,html=True),name='frontend')
    return app


app = create_app()
