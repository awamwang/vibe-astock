## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Tests

从仓库根目录直接跑 `pytest …` 即可；`pytest.ini` 已配置 `pythonpath = . vr`，不必再设 `PYTHONPATH`。

### Concurrency / lock safety

Before editing `threading.Lock` usage or multi-threaded IO (plugins, SSE, WebSocket): read `doc/development/lock-safety.md`. After changes run `pytest tests/test_lock_safety.py -q` and `python scripts/check_lock_holds.py`.
