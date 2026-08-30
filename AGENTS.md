## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Tests

从仓库根目录直接跑 `pytest …` 即可；`pytest.ini` 已配置 `pythonpath = . vr`，不必再设 `PYTHONPATH`。

### Concurrency / lock safety

Before editing `threading.Lock` usage or multi-threaded IO (plugins, SSE, WebSocket): read `doc/development/lock-safety.md`. After changes run `pytest tests/test_lock_safety.py -q` and `python scripts/check_lock_holds.py`.

### Release / version bump

版本号以仓库根目录 `VERSION` 为准，发布用 `scripts/release.py`：

```bash
python scripts/release.py status          # 检查各文件版本是否一致
python scripts/release.py sync            # 把 VERSION 同步到代码/徽章/文档
python scripts/release.py preview         # 预览自上次 tag 以来的提交归类
python scripts/release.py bump patch -m "摘要"   # 推进版本、写 CHANGELOG、commit、打 vX.Y.Z tag
```

`bump` 支持 `patch` / `minor` / `major` / 显式 `x.y.z`；常用选项：`--dry-run`、`--no-commit`、`--no-tag`、`--allow-dirty`。默认不 push，需自行 `git push && git push origin vX.Y.Z`。
