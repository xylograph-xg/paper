"""Actual fetch attempt timestamps, including transitions made by old workers."""
KINDS="'acquire','acquire_fallback','import'"

def install(catalog):
    with catalog.connect() as db:
        db.executescript(f"""
        CREATE TABLE IF NOT EXISTS fetch_attempt_times(
          job_id TEXT NOT NULL,attempt INTEGER NOT NULL,started_at TEXT,ended_at TEXT,
          result TEXT,PRIMARY KEY(job_id,attempt));
        CREATE TRIGGER IF NOT EXISTS fetch_attempt_started AFTER UPDATE OF state ON jobs
        WHEN NEW.kind IN ({KINDS}) AND NEW.state='running' AND OLD.state!='running'
        BEGIN INSERT OR REPLACE INTO fetch_attempt_times(job_id,attempt,started_at)
          VALUES(NEW.id,NEW.attempts,NEW.updated); END;
        CREATE TRIGGER IF NOT EXISTS fetch_attempt_ended AFTER UPDATE OF state ON jobs
        WHEN NEW.kind IN ({KINDS}) AND OLD.state='running' AND NEW.state!='running'
        BEGIN UPDATE fetch_attempt_times SET ended_at=NEW.updated,result=NEW.state
          WHERE job_id=NEW.id AND attempt=OLD.attempts; END;
        """)
        # Historical start times are unknown; never use queue creation time.
        db.execute(f"INSERT OR IGNORE INTO fetch_attempt_times SELECT id,attempts,CASE WHEN state='running' THEN updated END,CASE WHEN state IN ('done','deferred','failed','needs_manual') THEN updated END,state FROM jobs WHERE kind IN ({KINDS}) AND state IN ('running','done','deferred','failed','needs_manual') AND attempts>0")

def status(catalog):
    with catalog.connect() as db:
        rows=[dict(r) for r in db.execute("SELECT t.*,j.paper_id,j.kind,j.state,p.title FROM fetch_attempt_times t JOIN jobs j ON j.id=t.job_id LEFT JOIN papers p ON p.id=j.paper_id ORDER BY coalesce(t.ended_at,t.started_at) DESC")]
    return {'last_finished':next((r for r in rows if r['ended_at']),None),
            'active':[r for r in rows if r['state']=='running' and not r['ended_at']],
            'recent':[r for r in rows if r['ended_at']][:20], 'timezone':'Asia/Shanghai'}
