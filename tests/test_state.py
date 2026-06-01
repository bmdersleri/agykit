import os

import dashboard.state as state


def test_resolve_job_state_falls_back_and_copies_primary_bundle(monkeypatch, tmp_path):
    primary = tmp_path / "primary"
    fallback = tmp_path / "fallback"
    primary.mkdir()
    fallback.mkdir()

    src_db = primary / state.JOB_DB_NAME
    src_db.write_text("primary-db")
    (primary / state.OLD_JOB_DIR_NAME).mkdir()
    (primary / state.OLD_JOB_DIR_NAME / "job.json").write_text("{}")

    copied = {}

    monkeypatch.setattr(state, "_candidate_state_dirs", lambda: [str(primary), str(fallback)])
    monkeypatch.setattr(state, "_probe_sqlite_path", lambda db_path: db_path.startswith(str(fallback)))
    monkeypatch.setattr(
        state,
        "_copy_job_bundle",
        lambda source_dir, target_dir: copied.update({"source": source_dir, "target": target_dir}),
    )
    monkeypatch.setattr(state, "_STATE_CACHE", None)
    monkeypatch.setattr(state, "PRIMARY_STATE_DIR", str(primary))

    resolved = state.resolve_job_state()

    assert resolved["state_dir"] == str(fallback)
    assert resolved["db_path"] == os.path.join(str(fallback), state.JOB_DB_NAME)
    assert copied == {"source": str(primary), "target": str(fallback)}

